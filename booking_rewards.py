"""Apply an earned referral reward to one private booking."""
from datetime import datetime, timezone
from decimal import Decimal
import json
from zoneinfo import ZoneInfo

from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import text

from rewards import REWARD_TEXT


def define_models(db):
    class BookingReward(db.Model):
        booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), primary_key=True)
        code = db.Column(db.String(100), nullable=False, unique=True)

    class BookingRewardHistory(db.Model):
        id = db.Column(db.Integer, primary_key=True)
        client_id = db.Column(db.Integer, db.ForeignKey('client_account.id', ondelete='CASCADE'),
                              nullable=False, index=True)
        booking_id = db.Column(db.Integer, db.ForeignKey('booking.id', ondelete='SET NULL'), index=True)
        booking_reference = db.Column(db.String(100), nullable=False)
        code = db.Column(db.String(100), nullable=False)
        discount = db.Column(db.Numeric(10, 2), nullable=False)
        applied_at = db.Column(db.DateTime)
        returned_at = db.Column(db.DateTime)
        return_reason = db.Column(db.String(20))

    return BookingReward, BookingRewardHistory


def reward_discount(booking):
    try:
        data = json.loads(booking.event_schedule or '{}')
    except (ValueError, TypeError):
        return Decimal(0)
    if not isinstance(data, dict) or not data.get('booking_reward'):
        return Decimal(0)
    return sum((Decimal(day.get('reward_discount', '0')) for day in data.get('events', [])), Decimal(0))


def register(app, db, Booking, Account, BookingReward, History):
    signer = URLSafeSerializer(app.secret_key, salt='booking-referral-reward-v1')

    def local_time(value):
        if value is not None:
            return value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Europe/London'))

    def available(client_id):
        return db.session.execute(text("""
            SELECT referrals.code FROM referrals
            JOIN client_reward_owner AS owner ON owner.code = referrals.code
            WHERE owner.client_id = :client_id AND referrals.status = 'earned'
                AND referrals.reward_text = :reward
            ORDER BY referrals.reward_earned_date, referrals.id
            LIMIT 1
        """), {'client_id': client_id, 'reward': REWARD_TEXT}).scalar()

    def offer(client_id):
        code = available(client_id)
        return signer.dumps([client_id, code]) if code else ''

    def claim(client_id, booking, token, discount):
        try:
            offered_client_id, code = signer.loads(token)
        except (BadSignature, ValueError, TypeError):
            raise ValueError('Your 30-minute reward is no longer available. Review the booking and try again.') from None
        if offered_client_id != client_id:
            raise ValueError('This 30-minute reward is only available to the client who earned it.')
        redeemed_on = datetime.now(ZoneInfo('Europe/London')).date().isoformat()
        claimed = db.session.execute(text("""
            UPDATE referrals SET status = 'redeemed', reward_redeemed_date = :redeemed_on
            WHERE code = :code AND status = 'earned' AND reward_text = :reward
              AND EXISTS (SELECT 1 FROM client_reward_owner
                          WHERE code = :code AND client_id = :client_id)
        """), {'code': code, 'redeemed_on': redeemed_on, 'reward': REWARD_TEXT, 'client_id': client_id}).rowcount
        if claimed != 1:
            raise ValueError('Your 30-minute reward is no longer available. Review the booking and try again.')
        db.session.flush()
        db.session.add(BookingReward(booking_id=booking.id, code=code))
        db.session.add(History(client_id=client_id, booking_id=booking.id, booking_reference=booking.public_reference,
                               code=code, discount=discount, applied_at=datetime.utcnow()))

    def release(booking, *, deleted=False):
        record = db.session.get(BookingReward, booking.id)
        if record is None:
            if deleted:
                db.session.execute(db.update(History).where(History.booking_id == booking.id).values(booking_id=None))
            return
        FollowUp = app.extensions.get('booking_followup_model')
        if FollowUp is not None and db.session.get(FollowUp, booking.id) is not None:
            return
        history = History.query.filter_by(booking_id=booking.id).all()
        entry = next((row for row in history if row.code == record.code and row.returned_at is None), None)
        discount = reward_discount(booking)
        if entry is None:
            account = Account.query.filter(db.func.lower(db.func.trim(Account.email)) == booking.email.strip().casefold()).first()
            if account is not None:
                entry = History(client_id=account.id, booking_id=booking.id,
                                booking_reference=booking.public_reference, code=record.code)
                db.session.add(entry)
                history.append(entry)
        if entry is not None:
            entry.discount = discount
            entry.returned_at = datetime.utcnow()
            entry.return_reason = 'deleted' if deleted else booking.status.lower()
        if deleted:
            for row in history:
                row.booking_id = None

        data = json.loads(booking.event_schedule)
        for day in data['events']:
            day_discount = Decimal(day.pop('reward_discount', '0'))
            if day_discount:
                day['estimated_cost'] = str(Decimal(day['estimated_cost']) + day_discount)
        booking.total_event_cost += discount
        data.pop('booking_reward', None)
        booking.event_schedule = json.dumps(data)
        db.session.execute(text("""
            UPDATE referrals SET status = 'earned', reward_redeemed_date = NULL
            WHERE code = :code AND status = 'redeemed'
        """), {'code': record.code})
        db.session.delete(record)

    def booking_history(account):
        email = account.email.strip().casefold()
        records = db.session.execute(db.select(History, Booking).outerjoin(
            Booking, History.booking_id == Booking.id).where(History.client_id == account.id)).all()
        entries = []
        for entry, booking in records:
            can_open = booking is not None and booking.email.strip().casefold() == email
            active = entry.returned_at is None
            entries.append(dict(code=entry.code, reference=entry.booking_reference,
                                booking_id=booking.id if can_open else None,
                                discount=reward_discount(booking) if active and can_open else entry.discount,
                                returned=local_time(entry.returned_at), return_reason=entry.return_reason,
                                applied=local_time(entry.applied_at),
                                sort=entry.returned_at or entry.applied_at or datetime.min))

        # Rewards applied before the history table existed still have a booking association.
        legacy = db.session.execute(db.select(BookingReward, Booking).join(
            Booking, BookingReward.booking_id == Booking.id).where(
            db.func.lower(db.func.trim(Booking.email)) == email,
            ~db.exists().where(History.booking_id == Booking.id, History.returned_at.is_(None)))).all()
        for record, booking in legacy:
            entries.append(dict(code=record.code, reference=booking.public_reference, booking_id=booking.id,
                                discount=reward_discount(booking), returned=None, return_reason=None, applied=None,
                                sort=booking.submitted_at))
        return sorted(entries, key=lambda entry: entry['sort'], reverse=True)

    app.extensions.update(booking_reward_offer=offer, claim_booking_reward=claim,
                          release_booking_reward=release, booking_reward_history=booking_history)
    app.jinja_env.globals.update(booking_reward_discount=reward_discount, booking_reward_text=REWARD_TEXT)
