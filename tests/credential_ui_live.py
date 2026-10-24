"""Disposable, agent-owned cluster browser. No owner's browser/profile is used."""
import json,os
from pathlib import Path
from playwright.sync_api import sync_playwright

def main():
 c=json.loads(Path(os.environ['CRED_UI_FIXTURE']).read_text());host=c['host'];base='https://'+host
 posts=[]
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,args=['--host-resolver-rules=MAP '+host+' '+c['ingressIP'],'--ignore-certificate-errors-spki-list='+c['ingressSPKI']])
  context=browser.new_context(viewport={'width':1280,'height':1000});page=context.new_page()
  def login(page,user):
   page.goto(base+'/login',wait_until='domcontentloaded');page.locator('#login_username').fill(user);page.locator('#login_password').fill(c['passwords'][user]);page.locator('form[action="/login"] button[type="submit"]').click();page.wait_for_url(base+'/',wait_until='domcontentloaded');page.locator('#dsh-user-credentials').click();page.wait_for_selector('#profile option[value="azure-projects"]',state='attached')
  login(page,'cred-qa-a');page.on('request',lambda r:posts.append(r.post_data or '') if r.url.endswith('/api/user-credentials') and r.method=='POST' else None)
  page.locator('#password').fill(c['passwords']['cred-qa-a']);page.locator('#verify button').click();page.get_by_text('Identity confirmed for five minutes.',exact=True).wait_for()
  page.locator('#alias').fill('browser-qa');page.locator('#workspace').fill('one');page.locator('#profile').select_option('azure-projects');page.locator('#secret').fill('SYNTHETIC_BROWSER_CANARY_NOT_REAL');page.locator('#saveButton').click();page.locator('#list tr').filter(has_text='browser-qa').wait_for()
  assert page.locator('#secret').input_value()==''
  assert all('SYNTHETIC_BROWSER_CANARY_NOT_REAL' not in body for body in posts)
  assert any('secretEnvelope' in body for body in posts)
  assert page.evaluate('localStorage.length')==0 and page.evaluate('sessionStorage.length')==0
  page.screenshot(path='/tmp/credential-settings-desktop.png',full_page=True)
  second=browser.new_context();other=second.new_page();login(other,'cred-qa-b');assert other.locator('#list').inner_text().find('browser-qa')<0
  page.locator('#list tr').filter(has_text='browser-qa').get_by_role('button',name='Disable',exact=True).click();page.locator('#list tr').filter(has_text='browser-qa').get_by_text('(disabled)',exact=False).wait_for()
  page.on('dialog',lambda d:d.accept());page.locator('#list tr').filter(has_text='browser-qa').get_by_role('button',name='Delete',exact=True).click();page.locator('#list tr').filter(has_text='browser-qa').wait_for(state='detached')
  page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'Mobile horizontal overflow';page.screenshot(path='/tmp/credential-settings-mobile.png',full_page=True)
  browser.close()
 print(json.dumps({'realBrowserForms':True,'browserEncryptionVerifiedInRequest':True,'rawProviderSecretAbsentFromRequests':True,'secretInputCleared':True,'browserStorageEmpty':True,'twoUserIsolation':True,'disableDeleteUI':True,'mobileFits':True,'agentOwnedClusterBrowser':True,'tlsIngressPublicKeyPinned':True,'realProviderCredentialsUsed':False}))

if __name__=='__main__':main()
