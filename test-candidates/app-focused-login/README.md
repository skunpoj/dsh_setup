# App-focused DSH sign-in — verified isolated Test release

The new Test issuer and demonstration apps are deployed with source identity `fec53f838ef52984f6ea8977f8ac0c3280c99279ebfffa5eee13539f0a6a512a` and `auth_proxy.js` SHA-256 `8ba09e26058f8ae610ef89b35ef9810ce7fce914337d78e22d19f83c31601059`. The actual mounted files match all twelve reviewed source hashes. The pinned Node runtime image is unchanged; this is a source ConfigMap rollout, not a new application image build.

## Actual Test links

| Flow | URL |
| --- | --- |
| Gated app | https://app-signin-gated-test.aiportal.bot.or.th/ |
| App-focused issuer screen | https://dsh-app-signin-test.aiportal.bot.or.th/login?app=app-signin-gated-test |
| Public app | https://app-signin-public-test.aiportal.bot.or.th/login |

These are isolated Test demonstrations using synthetic accounts and their own persistent session store. Do not enter normal DSH credentials into this Test issuer. No Main account/session data was copied. The existing real-normal-login bridge remains unchanged and was not retired. Visitors open an app link directly; a separate proxy manager is not a required visitor step.

## Behavior and verification

The gated flow hides workspace, terminal, Jupyter and registration options, authenticates the mapping owner in its configured environment, and returns to the registered alias. Public access bypasses the DSH visitor gate while preserving destination authentication. Password verification, audit/account checks and persistent session creation use the normal issuer implementation; the deployed Test instance has its own synthetic account store.

The final Linux run passed **82 tests**, plus **three additional asynchronous verifier race cases**. Tests use the actual configured alias names and Host headers. Live API checks verified wrong/correct passwords, exact returned identity and content, both saved access modes, credential stripping, real WebSocket echo and logout revocation. The feature-off and return-to-on rehearsal preserved account, route, mapping, session and backup bytes and returned the same authenticated application content afterward.

**Native browser submission remains unverified.** The app page renders correctly, but two IAB profiles and a harmless local form control did not submit through the tested semantic or coordinate actions. That observation is not proof of an application defect or of every browser's behavior. A human manual check remains pending. See qualification/FINAL_TEST_SUMMARY.json and the actual API/recovery reports; do not claim complete browser end-to-end acceptance.

## Safety and history

The form challenge is browser-bound, single-use and expires after five minutes. Mapping ownership/stamp is rechecked after asynchronous password verification. Changed mappings fail closed; challenge-capacity failures cannot crash the gateway. The unchanged routing-name predicate rejects reserved `dsh-` aliases. The initial invalid-alias rollout and its evidence are preserved; the own registry migration kept an exact private backup and changed only its two keys.

Recovery keeps this source and switches only `DSH_APP_LOGIN_ENABLED` off/on using reviewed own-UID/resourceVersion/full-spec fences. It retains the corrected aliases, external/Public routing and persistent sessions. Prior Main sources without external proxy support are not the preferred fallback. Reviewed operator sources are under qualification/operators; the private execution plans, synthetic credentials, keys and cookie jars are not published.

The source preserves the qualified Main auth/capacity cutoff 7a682/c59b and signup helper eb707. A separate authorized Main helper hardening later became 736e6b. Test registration is disabled; future Main promotion must preserve that current helper rather than overwrite Main with this frozen snapshot. SMP Test intentionally uses triage V4 while Production keeps the original prompt. Both watchers were freshly checked enabled. No Main/Production promotion or historical resend was performed by this rollout.

PPTX, English video and Test documentation-site publication were not changed by this Test qualification. Original evidence is preserved under qualification/archive and the versioned private output folders.
