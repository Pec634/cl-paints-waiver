"""Credit paid till visits through the existing one-person-per-event loyalty ledger."""
from datetime import datetime, timezone
import json
from zoneinfo import ZoneInfo
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError


class PosLoyalty:
    def __init__(self, app, db, models, Account, Participant, Waiver, Event):
        self.app, self.db = app, db
        _, self.Balance, self.Visit, self.Custodian, _ = models
        self.Account, self.Participant, self.Waiver, self.Event = Account, Participant, Waiver, Event

    def waiver_account(self, waiver, custodian):
        account_id = custodian.client_id if custodian else waiver.responsible_account_id
        if account_id is not None:
            return self.db.session.get(self.Account, account_id)
        return self.Account.query.filter(func.lower(func.trim(self.Account.email)) ==
                                         waiver.responsible_email.strip().lower()).first()

    def events(self):
        today = datetime.now(ZoneInfo('Europe/London')).date()
        public = self.app.extensions['kiosk_public_event']
        return [event for event in self.Event.query.filter(self.Event.event_date == today,
            self.Event.status.in_(['Open', 'Closing Soon'])).order_by(self.Event.name).all() if public(event)]

    def people(self, waiver):
        originals = self.Participant.query.filter_by(waiver_id=waiver.id).all()
        transferred = self.Participant.query.join(self.Custodian,
            self.Custodian.participant_id == self.Participant.id).filter(self.Custodian.waiver_id == waiver.id).all()
        return [person for person in {p.id:p for p in originals+transferred}.values()
            if not (owner := self.db.session.get(self.Custodian, person.id)) or owner.waiver_id == waiver.id]

    def prepare(self, waiver, form):
        ids = set(form.getlist('loyalty_participant_id', type=int))
        if not ids:
            return None, []
        allowed = {person.id for person in self.people(waiver)} if waiver else set()
        if not ids <= allowed:
            raise ValueError('Choose loyalty participants belonging to the linked waiver.')
        event_id = form.get('loyalty_event_id', type=int)
        if event_id not in {event.id for event in self.events()}:
            raise ValueError('Choose an open public event for today to award loyalty points.')
        return event_id, sorted(ids)

    def claim_reward(self, sale, person_id):
        changed = self.Balance.query.filter_by(participant_id=person_id, points=3).update(
            {'points': 0}, synchronize_session=False)
        if not changed:
            raise ValueError('This free face paint is no longer available. Check the participant?s balance.')
        if sale.loyalty_event_id:
            if self.Visit.query.filter_by(participant_id=person_id, event_id=sale.loyalty_event_id).first():
                raise ValueError('This participant has already checked in at this loyalty event.')
            waiver = self.db.session.get(self.Waiver, sale.waiver_id)
            owner = self.db.session.get(self.Custodian, person_id)
            email = waiver.responsible_email.strip().lower()
            account = self.waiver_account(waiver, owner)
            if not account:
                account = self.Account(email=email, first_name=waiver.responsible_first_name,
                    last_name=waiver.responsible_last_name)
                self.db.session.add(account)
                self.db.session.flush()
            self.db.session.add(self.Visit(participant_id=person_id, event_id=sale.loyalty_event_id,
                client_id=account.id, status='free' if sale.status == 'Paid' else 'pending',
                confirmed_at=sale.paid_at, pos_sale_id=sale.id))

    def release_reward(self, sale, person_id):
        self.Visit.query.filter_by(pos_sale_id=sale.id, participant_id=person_id, status='pending').delete()
        self.Balance.query.filter_by(participant_id=person_id).update({'points': 3}, synchronize_session=False)

    def award(self, sale):
        if sale.status != 'Paid' or sale.loyalty_result_json is not None:
            return
        ids = json.loads(sale.loyalty_participants_json or '[]')
        results = []
        for item in json.loads(sale.items_json):
            person_id = item.get('reward_participant_id')
            if person_id:
                self.Visit.query.filter_by(pos_sale_id=sale.id, participant_id=person_id, status='pending').update(
                    {'status': 'free', 'confirmed_at': sale.paid_at})
                results.append(dict(participant_id=person_id, name=sale.participant_name,
                    points=0, redeemed=True, message='Free face paint redeemed'))
        if not sale.loyalty_event_id:
            ids = []
        if not ids and not results:
            return
        for person_id in ids:
            person = self.db.session.get(self.Participant, person_id)
            name = f'{person.first_name} {person.last_name}' if person else f'Member #{person_id}'
            result = dict(participant_id=person_id, name=name, points=0)
            try:
                with self.db.session.begin_nested():
                    if not person:
                        raise ValueError('Participant no longer available')
                    owner = self.db.session.get(self.Custodian, person_id)
                    waiver = self.db.session.get(self.Waiver, owner.waiver_id) if owner else person.waiver
                    if not waiver or waiver.id != sale.waiver_id:
                        raise ValueError('Participant has moved to another waiver')
                    if self.Visit.query.filter_by(participant_id=person_id, event_id=sale.loyalty_event_id).first():
                        raise ValueError('Already checked in at this event; no extra point')
                    balance = self.db.session.get(self.Balance, person_id)
                    points = balance.points if balance else 0
                    if points >= 3:
                        raise ValueError('3/3 points — free paint ready; no extra point added')
                    account = self.waiver_account(waiver, owner)
                    if not account:
                        account = self.Account(email=waiver.responsible_email.strip().lower(),
                            first_name=waiver.responsible_first_name, last_name=waiver.responsible_last_name)
                        self.db.session.add(account)
                        self.db.session.flush()
                    if balance:
                        changed = self.Balance.query.filter_by(participant_id=person_id, points=points).update(
                            {'points':points+1}, synchronize_session=False)
                        if changed != 1:
                            raise ValueError('Balance changed during checkout; review loyalty history')
                        self.db.session.expire(balance)
                    else:
                        self.db.session.add(self.Balance(participant_id=person_id, points=1))
                    self.db.session.add(self.Visit(participant_id=person_id, event_id=sale.loyalty_event_id,
                        client_id=account.id, status='point', confirmed_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        pos_sale_id=sale.id))
                    self.db.session.flush()
                    result.update(points=1, message=f'1 point added · {points+1}/3 points')
            except ValueError as error:
                result['message'] = str(error)
            except IntegrityError:
                result['message'] = 'Already credited or balance changed; review loyalty history'
            results.append(result)
        sale.loyalty_result_json = json.dumps(results)

    def balances(self, people):
        ids = [person.id for person in people]
        return {row.participant_id:row.points for row in self.Balance.query.filter(self.Balance.participant_id.in_(ids)).all()}
