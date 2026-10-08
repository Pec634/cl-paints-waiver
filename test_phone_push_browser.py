import unittest
import test_native_form_browser as browsers

@unittest.skipUnless(browsers.EDGE.is_file(),'Microsoft Edge is not installed')
class PhonePushBrowserTest(unittest.TestCase):
    def test_mobile_permission_preferences_and_disable(self):
        fixture=browsers.NativeFormBrowserTest(); fixture.setUp()
        try:
            page=fixture.fixture.admin.get('/admin/notifications')
            fixture.browser(page.data, '''
              const pause = () => new Promise(resolve => setTimeout(resolve, 50));
              await pause();
              assert(!document.querySelector('[data-push-enable]').disabled, 'Enable available');
              assert(window.pushCalls.length === 0, 'No permission requested before a click');
              document.querySelector('#phone-notifications input[value="updates"]').checked = false;
              document.querySelector('[data-push-enable]').click(); await pause();
              assert(window.pushCalls[0] === 'permission', 'Permission follows explicit click');
              const saved = window.pushCalls.find(call => call.method === 'POST');
              assert(saved && !saved.data.preferences.includes('updates'), 'Selected categories saved');
              assert(saved.csrf === 'browser-token', 'CSRF included');
              assert(document.querySelector('[data-push-status]').textContent.includes('enabled'), 'Success status');
              document.querySelector('[data-push-disable]').click(); await pause();
              assert(window.pushCalls.some(call => call.method === 'DELETE'), 'Server disabled');
              assert(window.pushCalls.includes('unsubscribe'), 'Browser unsubscribed');
            ''',width=390,setup='''
              window.pushCalls=[];
              Object.defineProperty(window,'isSecureContext',{value:true});
              window.PushManager=function(){};
              window.Notification={requestPermission:async()=>{window.pushCalls.push('permission');return 'granted';}};
              const sub={endpoint:'https://fcm.googleapis.com/test',toJSON:()=>({endpoint:'https://fcm.googleapis.com/test',keys:{}}),unsubscribe:async()=>{window.pushCalls.push('unsubscribe');}};
              let active=null;
              const registration={pushManager:{getSubscription:async()=>active,subscribe:async()=>{active=sub;return sub;}}};
              Object.defineProperty(navigator,'serviceWorker',{value:{register:async()=>registration,ready:Promise.resolve(registration)}});
              window.fetch=async(url,options)=>{
                if(options) window.pushCalls.push({method:options.method,data:JSON.parse(options.body),csrf:options.headers['X-CSRF-Token']});
                return {ok:true,json:async()=>options?{ok:true}:{ready:true,public_key:'BA',csrf:'browser-token'}};
              };
            ''')
        finally: fixture.tearDown()
