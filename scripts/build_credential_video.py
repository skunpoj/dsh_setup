"""Generate a captioned design supplement, not a product demo or live recording."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import textwrap

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs' / 'videos'
SCENES = [
 ('Secrets outside chat', 'DESIGN ONLY: the settings page and credential broker are not deployed. The harness receives an alias and allowed actions, never the secret value.'),
 ('Add a connection privately', 'Planned flow: Settings > Credentials, reauthenticate, then use a dedicated HTTPS form or OAuth consent. Select workspace, environment, resource, actions and expiry.'),
 ('Authorize a typed operation', 'The broker verifies the user and workload, checks policy and uses an encrypted vault. A connector performs the approved action. No generic secret retrieval is exposed to the model.'),
 ('1. Prevent external leakage', 'Separate internal and Internet connectors. Fixed destinations, restricted broker egress and no external fallback. Never inject reusable secrets into the ordinary harness terminal.'),
 ('2. Prevent damage or excessive access', 'Allow only scoped resources and actions. Consequential changes need explicit confirmation bound to the exact request. Private deployment tools never inherit admin credentials.'),
 ('3. Keep results contained', 'Return bounded, filtered results. Central audit records actor, action and outcome, excluding tokens, passwords and conversation bodies. Other users cannot use the credential.'),
 ('Expire, disable and replace', 'Users manage metadata and replace secrets without revealing stored values. Disable blocks new use. Provider revocation is tracked; completed actions cannot be recalled.'),
 ('Verify before release', 'Two-user negative tests, output-leak canaries, replay denial, network tests and encrypted restore are required. Source policy tests alone do not prove deployed security.'),
]

def stamp(seconds):
    return f'{seconds//3600:02}:{seconds//60%60:02}:{seconds%60:02}.000'

def main():
    OUT.mkdir(exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 34)
    heading = ImageFont.truetype('C:/Windows/Fonts/arialbd.ttf', 48)
    small = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 24)
    with tempfile.TemporaryDirectory(prefix='credential-design-') as temp:
        tmp = Path(temp)
        for index, (title, body) in enumerate(SCENES):
            im = Image.new('RGB', (1280, 720), '#f3f6f9')
            draw = ImageDraw.Draw(im)
            draw.rectangle((0,0,1280,130), fill='#003366')
            draw.text((55,35), title, font=heading, fill='white')
            for row,line in enumerate(textwrap.wrap(body, 61)):
                draw.text((65,205+row*55), line, font=font, fill='#16324f')
            draw.text((65,620), 'Proposed architecture | Captioned design supplement | No live UI shown', font=small, fill='#4c6075')
            draw.text((1120,665), f'{index+1} / {len(SCENES)}',font=small,fill='#003366')
            im.save(tmp / f'{index:02}.png')
        target=OUT/'credential-management-design.mp4'
        subprocess.run([ffmpeg,'-y','-v','error','-framerate','1/12','-i',str(tmp/'%02d.png'),
                        '-c:v','libx264','-r','24','-pix_fmt','yuv420p','-movflags','+faststart',str(target)],check=True)
        subprocess.run([ffmpeg,'-v','error','-i',str(target),'-f','null','-'],check=True)
        for second in [1,85]:
            subprocess.run([ffmpeg,'-y','-v','error','-ss',str(second),'-i',str(target),'-frames:v','1',str(OUT/f'credential-design-check-{second}.png')],check=True)
    cues=['WEBVTT\n']
    for i,(title,body) in enumerate(SCENES):
        cues.append(f'{stamp(i*12)} --> {stamp((i+1)*12)}\n{title}. {body}\n')
    (OUT/'credential-management-design.vtt').write_text('\n'.join(cues),encoding='utf-8')
    (OUT/'credential-management-design-transcript.txt').write_text('\n\n'.join(t+'. '+b for t,b in SCENES),encoding='utf-8')
    receipt={'type':'captioned design supplement; silent; no live UI', 'seconds':96,'scenes':8,
             'decodedEntireVideo':True,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'bytes':target.stat().st_size}
    (OUT/'credential-management-design-verification.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(receipt))

if __name__=='__main__': main()
