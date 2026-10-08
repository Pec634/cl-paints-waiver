import json
import unittest
import test_business_tools as fixtures
import test_native_form_browser as browsers
from login_reviews import validate_reviews


class LoginReviewsTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.BusinessToolsTest();self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_admin_save_escape_remove_and_csrf(self):
        admin=self.fixture.admin
        admin.get('/admin/settings')
        with admin.session_transaction() as session:
            token=session['settings_csrf']
        payload=dict(section='login_reviews',review_name_0='Reviewer',review_text_0='<script>alert(1)</script>',review_rating_0='4',review_detail_0='Birthday')
        self.assertEqual(admin.post('/admin/settings',data=payload).status_code,400)
        payload['csrf_token']=token
        self.assertEqual(admin.post('/admin/settings',data=payload).status_code,302)
        visitor=fixtures.main.app.test_client()
        page=visitor.get('/client/login').data
        self.assertIn(b'&lt;script&gt;',page)
        self.assertIn(b'4 out of 5 stars',page)
        self.assertNotIn(b'<script>alert(1)</script>',page)
        self.assertEqual(admin.post('/admin/settings',data=dict(section='login_reviews',csrf_token=token)).status_code,302)
        self.assertNotIn(b'client-review-carousel',visitor.get('/client/login').data)

    @unittest.skipUnless(browsers.EDGE.is_file(),'Microsoft Edge is not installed')
    def test_carousel_controls_rotation_and_reduced_motion(self):
        setting=fixtures.main.BusinessSetting(key='login_reviews',value=json.dumps([
            dict(name='First reviewer',text='First review',detail='',rating=5),
            dict(name='Second reviewer',text='Second review',detail='',rating=4)]))
        fixtures.main.db.session.add(setting);fixtures.main.db.session.commit()
        page=fixtures.main.app.test_client().get('/client/login')
        browsers.NativeFormBrowserTest().browser(page.data, '''
            const slides=[...document.querySelectorAll('[data-review-slide]')];
            const visible=()=>slides.findIndex(slide=>!slide.hidden);
            assert(visible()===0,'First review visible');
            assert(window.reviewInterval===7000,'Seven second rotation');
            window.reviewTick();assert(visible()===1,'Automatic rotation advances');
            document.querySelector('[data-review-next]').click();assert(visible()===0,'Next wraps');
            document.querySelector('[data-review-prev]').click();assert(visible()===1,'Previous wraps');
            const pause=document.querySelector('[data-review-pause]');pause.click();
            assert(pause.textContent==='Resume rotation','Pause available');
            document.documentElement.classList.add('portal-reduced-motion');
            document.dispatchEvent(new Event('visibilitychange'));
            assert(pause.disabled && pause.textContent==='Auto-rotation off','Reduced motion stops rotation');
            assert(document.documentElement.scrollWidth<=innerWidth,'Reviews fit phone');
        ''',width=390,setup='window.setInterval=(callback,delay)=>{window.reviewTick=callback;window.reviewInterval=delay;return 1;};')

    def test_invalid_rating_and_incomplete_reviews(self):
        for payload in [dict(review_name_0='Name'),dict(review_name_0='Name',review_text_0='Text',review_rating_0='9')]:
            with self.assertRaises(ValueError):validate_reviews(payload)
        self.assertEqual(json.loads(validate_reviews({})),[])
