import unittest
import test_loyalty as fixtures
import test_native_form_browser as browsers
import rewards

main=fixtures.main

class DashboardReferencesTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.LoyaltyTest(); self.fixture.setUp()
    def tearDown(self): self.fixture.tearDown()
    def test_owned_references_codes_and_transfer_privacy(self):
        rewards.execute("INSERT INTO referrals(customer_name,code,original_event_date,expires_date,status) VALUES ('Test','FRIEND-123','2026-01-01','2027-01-01','active')")
        main.db.session.add(main.ClientRewardOwner(code='FRIEND-123',client_id=self.fixture.account.id))
        private=self.fixture.make_waiver('other@example.com','OTHER-PRIVATE')
        other=main.ClientAccount(email='other@example.com',first_name='Other',last_name='Client')
        main.db.session.add(other); main.db.session.flush()
        main.db.session.add(main.loyalty_models[3](participant_id=self.fixture.person.id,client_id=other.id,waiver_id=private.id))
        main.db.session.commit()
        page=self.fixture.client.get('/client/')
        self.assertEqual(page.status_code,200)
        self.assertIn(self.fixture.waiver.public_reference.encode(),page.data)
        self.assertIn(self.fixture.other.loyalty_reference.encode(),page.data)
        self.assertIn(b'FRIEND-123',page.data)
        self.assertNotIn(private.public_reference.encode(),page.data)
        self.assertNotIn(self.fixture.person.loyalty_reference.encode(),page.data)
    @unittest.skipUnless(browsers.EDGE.is_file(),'Microsoft Edge is not installed')
    def test_reference_cards_at_phone_width(self):
        page=self.fixture.client.get('/client/')
        browsers.NativeFormBrowserTest().browser(page.data, '''
            const section=document.querySelector('#your-references');
            assert(section.closest('.client-welcome'),'Codes belong to welcome header');
            assert(document.querySelector('.client-main > header, .client-main > section').classList.contains('client-welcome'),'Welcome first dashboard section');
            assert(section && section.querySelectorAll('h3').length===4,'Four clearly labelled reference groups');
            for(const code of section.querySelectorAll('.dashboard-reference-code')) {
              assert(getComputedStyle(code).userSelect==='text','Code selectable');
              assert(code.getBoundingClientRect().right<=innerWidth+1,'Code fits phone width');
            }
            assert(section.textContent.includes('No refer-a-friend code linked yet'),'Helpful referral empty state');
            const dropdowns=[...document.querySelectorAll('[data-dashboard-accordion] > details')];
            assert(dropdowns.length>=3,'Dashboard sections are collapsible');
            const counts=document.querySelector('.client-main > .client-summary');
            assert(counts && !counts.closest('details'),'Request and reward counts always visible');
            assert(counts.previousElementSibling.classList.contains('client-welcome'),'Counts directly below welcome');
            const labels=dropdowns.map(item=>item.querySelector('summary').textContent.trim());
            assert(labels.every((label,index)=>index===0 || labels[index-1].localeCompare(label,'en-GB',{sensitivity:'base'})<=0),'Dropdowns alphabetically ordered');
            assert(dropdowns.every(item=>!item.open),'Sections initially collapsed');
            dropdowns[0].querySelector('summary').click();
            assert(dropdowns[0].open,'First section opens');
            dropdowns[1].querySelector('summary').click();
            assert(dropdowns[1].open && !dropdowns[0].open,'Only one section opens at a time');
        ''',width=390)
