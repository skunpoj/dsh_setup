# DSH RDT Pilot Security-Control Assessment

**Assessment date:** 15 October 2026, 13:03 ICT  
**Evidence boundary:** This is the 13:03 ICT assessment snapshot, retained with its observed image digest and test results. Later deployments or model-context changes do not constitute a fresh verification of these security controls. The detailed design below incorporates the README security architecture in this report; it is not a verbatim copy of the entire README.

**Scope:** Current Production DSH environment gateway, `dsh-secure`, `dsh-internet`, package-transfer design, authentication boundary, workspaces, and execution containment in Kubernetes namespace `llm`  
**Assessment objective:** Determine whether the current DSH design limits the consequences of using Harness or generated code with RDT sufficiently for the proposed pilot. This assessment does not claim that Harness or generated code is intrinsically safe.

## Executive assessment

The current DSH deployment **partially addresses** the three required controls. It provides a working restricted-egress environment, separates the Internet and protected workspaces, authenticates entry through a gateway, and constrains both execution pools to a non-root container identity. These controls materially reduce external leakage and cross-environment contamination.

The deployment does **not yet satisfy the complete RDT pilot control set**. Two material controls remain unverified or absent:

1. RDT has not been demonstrated as a limited, read-only snapshot or view accessed through a dedicated non-admin data identity.
2. Authenticated users within the same execution environment are not strongly isolated from one another; they share that environment's DSH process and mounted workspace/state volumes.

Accordingly, the present state should be described as **environment-level containment implemented, RDT data-level and per-user containment incomplete**.

## Detailed control design: ใช้อะไร วางตรงไหน และปิดความเสี่ยงอย่างไร

ส่วนนี้รวมสาระการออกแบบจาก README เข้ามาในรายงานโดยตรง เพื่อให้ผู้พิจารณาเห็นทั้งสถาปัตยกรรม วิธีใช้งาน จุดควบคุม ผู้รับผิดชอบ และวิธีพิสูจน์ผลโดยไม่ต้องเปิดเอกสารอื่นประกอบ

### ภาพรวมเส้นทางการทำงาน

```text
ผู้ใช้ที่ผ่านการยืนยันตัวตน
        |
        v
DSH Environment Gateway
  - ตรวจ username/password
  - ตั้ง HttpOnly session cookie
  - เลือก environment โดยค่าเริ่มต้นเป็น Internet Off
  - ผูก session เดิมให้ไป backend เดิมเสมอ
        |
        +------------------------------+
        |                              |
        v                              v
No Internet / Internal             Internet
  dsh-secure                         dsh-internet
  - RDT/protected work               - download package
  - no public egress                 - external research/staging
  - protected workspace              - separate staging workspace
        |                              |
        |                              v
        |                         /packages/incoming
        |                              |
        |                    operator review + SHA-256
        |                              |
        |                    suspended promotion Job
        |                              |
        v                              v
 /packages/approved <---------- approved artifacts only
   read-only mount
        |
        +----> Internal LiteLLM ----> shared four-GPU model
```

ทั้งสอง environment ใช้ gateway และโมเดลภายในร่วมกันเพื่อประหยัดทรัพยากร GPU แต่ไม่ใช้ writable workspace, session/history state, attachment, launch token หรือพื้นที่ package ร่วมกัน การเลือก Internet ไม่ทำให้ Internet pod เห็น RDT หรือ Secure workspace

### Control 1 — ป้องกันข้อมูลรั่วออกภายนอก

| ความเสี่ยง | ใช้อะไรควบคุม | วางตรงไหน | วิธีทำงาน | ท่าทดสอบเพื่อปิดความเสี่ยง |
|---|---|---|---|---|
| Harness หรือ generated code ติดต่อ Internet | Kubernetes `NetworkPolicy` แบบ restricted egress | ครอบ `dsh-secure` ด้วย label `egress-mode=offline` | อนุญาตเฉพาะ DNS และ LiteLLM ภายใน TCP 4000; traffic อื่นไม่มี allow rule | รัน HTTPS/DNS/connection test ไป GitHub, public package registry และ public IP จาก Secure แล้วต้องล้มเหลว |
| ผู้ใช้กดผิดหรือไม่ส่งค่า environment | Fail-closed routing | `dsh-environment-gateway` | ค่า default, ค่าว่าง และค่าที่ไม่รู้จักถูกส่งไป No Internet/Internal | ล็อกอินโดยไม่เลือกค่าและส่งค่าปลอม ตรวจ backend/session ว่าเป็น Secure |
| Terminal, WebSocket หรือ app proxy หลุดไปคนละ environment | Session-sticky gateway routing | Gateway ระหว่าง Ingress กับ execution pools | HTTP, WebSocket, terminal และ dynamic app ของ login session เดียวกันไป pool เดียวตลอดอายุ session | เปิด terminal และ proxied app ใน session เดียวกัน แล้วอ่าน backend marker/launch token ต้องตรงกันทั้งหมด |
| Internet environment เข้าถึง RDT | แยก PVC และไม่ mount ข้าม environment | `dsh-secure-workspace` เทียบกับ `dsh-internet-staging` | Internet pod ไม่มี volume mount ของ Secure workspace, state หรือ attachment | ตรวจ pod spec และพยายามอ่าน path/volume ของ Secure จาก Internet ต้องไม่พบ |
| DSH เลือก external model/provider | Internal LiteLLM endpoint, Secret และ Secure egress deny | DSH model profile และ `dsh-runtime-secrets` | คำขอ inference วิ่งไป `litellm.llm.svc.cluster.local:4000`; Secure NetworkPolicy กัน public provider | ตรวจ active model catalog และ runtime configuration; เรียก internal model ต้องสำเร็จ และเรียก public model endpoint ต้องล้มเหลว |

**สิ่งที่ปิดแล้ว:** Network-level Internet denial ของ Secure ถูกทดสอบจริง, Internet pool ยังออก GitHub ได้, และสอง pool ไม่ mount workspace ของกันและกัน  
**สิ่งที่ต้องปิดต่อ:** ลบหรือ disable `deepseek-official` และ external provider อื่นจาก Secure catalog เพื่อให้ไม่มี fallback ทั้งใน configuration และ infrastructure แม้ปัจจุบัน NetworkPolicy จะบล็อกเส้นทางนั้นอยู่แล้ว

### Control 2 — ป้องกันการแก้ไขข้อมูลต้นทางหรือเข้าถึงเกินสิทธิ

| ความเสี่ยง | ใช้อะไรควบคุม | วางตรงไหน | วิธีทำงาน | ท่าทดสอบเพื่อปิดความเสี่ยง |
|---|---|---|---|---|
| Generated code ใช้สิทธิระดับผู้ดูแลระบบ | Kubernetes `securityContext` | ทั้ง `dsh-secure`, `dsh-internet` และ promotion Job | รันด้วย UID/GID 10001, `runAsNonRoot`, ห้าม privilege escalation และ drop Linux capabilities ทั้งหมด | ตรวจ runtime UID; ทดลอง `sudo`, mount, capability-sensitive action และเขียน system path ต้องล้มเหลว |
| Generated code แก้ไข RDT ต้นทาง | Dedicated RDT identity + read-only snapshot/view | ชั้น data source ก่อน mount หรือ database connection เข้า Secure | identity อ่านเฉพาะ dataset/field/snapshot ที่อนุมัติ ไม่มี INSERT/UPDATE/DELETE และไม่มี write permission ที่ source | ทดลองแก้ไข ลบ สร้าง table/file และ overwrite source ต้องถูกปฏิเสธ พร้อมเก็บ audit log |
| อ่านข้อมูลนอก RDT scope | Allow-listed view/path และ deny-by-default permission | RDT database/schema, storage export หรือ read-only volume | expose เฉพาะ snapshot/view ที่ pilot ต้องใช้ ไม่ mount parent directory หรือ credential ของระบบอื่น | ทดลอง enumerate schema, parent path, sibling dataset และ unrelated service ต้องล้มเหลว |
| ผลลัพธ์ปนกับข้อมูลต้นทาง | แยก source กับ results mount | Secure pod เช่น `/rdt/source` แบบ read-only และ `/workspace/results/<user-or-case>` แบบ writable | code อ่านจาก source และเขียนได้เฉพาะ results/work folder | ตรวจ mount flags แล้วทดสอบ write ทั้งสองตำแหน่ง: source ต้อง fail, results ต้อง pass |
| Package จาก Internet แอบแก้ Secure | Incoming/approved PVC, approval manifest, SHA-256 และ mode `0444` | `/packages/incoming`, promotion Job, `/packages/approved` | Internet ดาวน์โหลดอย่างเดียว; operator ตรวจ origin/hash; Job ปฏิเสธ path traversal, ไฟล์หาย และ hash ไม่ตรง; Secure อ่าน approved cache เท่านั้น | ใช้ไฟล์ hash ถูกต้องต้อง promote ได้; hash ผิด, path `../`, absolute path และไฟล์เกิน manifest ต้องถูกปฏิเสธ |
| Process ใช้ทรัพยากรเกินควบคุม | CPU/RAM limit และ probe | DSH containers | จำกัด 4 CPU/8 GiB ต่อ container และไม่ส่ง traffic ไป process ที่ยังไม่ ready | รันทดสอบ load ภายใต้ limit, ตรวจ throttling/OOM/restart และยืนยัน gateway หยุดส่ง traffic ระหว่าง unready |

**สิ่งที่ปิดแล้ว:** non-root execution, no privilege escalation, capability drop, resource limits, workspace แยกตาม environment และ controlled package promotion  
**สิ่งที่ต้องปิดต่อ:** ปัจจุบันยังไม่มีหลักฐานว่า RDT ถูกนำเข้าผ่าน dedicated read-only identity/snapshot/view และยังไม่ได้ทำ negative test สำหรับ source write กับ out-of-scope read จึงยังปิด Control 2 ไม่ได้

### Control 3 — จำกัดรายงาน ประวัติ และไฟล์ให้อยู่ในผู้ใช้ pilot ที่ได้รับอนุญาต

| ความเสี่ยง | ใช้อะไรควบคุม | วางตรงไหน | วิธีทำงาน | ท่าทดสอบเพื่อปิดความเสี่ยง |
|---|---|---|---|---|
| บุคคลภายนอกเข้าหน้า DSH/report | Authenticated gateway และ session cookie | Ingress หน้า execution pools | unauthenticated request เข้าได้เฉพาะ login; pool รับ traffic จาก gateway | เปิด report, terminal, app proxy และ API โดยไม่มี cookie ต้องได้ login/401/403 ไม่ใช่เนื้อหา |
| ผู้ใช้นอก pilot สมัครเอง | Named-user allow-list หรือ corporate IdP group | Gateway account provisioning | ปิด public self-registration; เฉพาะรายชื่อหรือ group pilot จึงสร้าง session ได้ | account นอก list/group ต้อง login และสร้าง account ไม่ได้; account pilot ต้องเข้าได้ |
| ผู้ใช้ A เห็นไฟล์/session ของ B | Per-user pod + per-user workspace/state PVC หรือ sandbox ที่ให้ isolation เทียบเท่า | หลัง gateway ก่อน shared LiteLLM | gateway map identity ไป dedicated runtime; user แต่ละคนมี workspace, history, attachment และ token ของตนเอง | A พยายาม list/read/modify B workspace, report, attachment และ session ID ต้อง fail ทุกช่องทาง รวม terminal/tool/API |
| รายงานถูก publish/export อัตโนมัติ | ไม่มี public route, no scheduler/export credential และ Secure egress deny | app proxy, scheduled jobs, storage integration และ Secure pod | report เปิดผ่าน authenticated gateway เท่านั้น; ไม่มี credential หรือ job ส่งออกภายนอก | ตรวจ CronJob/automation/config; สร้าง report แล้วทดสอบ anonymous URL, direct service URL และ outbound upload ต้อง fail |
| Internet session เห็น Secure history | Separate state PVC และ launch token | `/state` และ token volume ของแต่ละ pool | history/session/attachment คงอยู่ใน environment ที่สร้าง ไม่มี automatic copy เมื่อเปลี่ยน environment | สร้าง marker ใน Secure แล้ว login ใหม่เข้า Internet; marker ต้องไม่ปรากฏใน file, history, attachment หรือ search |

**สิ่งที่ปิดแล้ว:** authenticated gateway, HttpOnly session, environment-sticky routing, state/workspace separation ระหว่าง Secure กับ Internet และ Secure egress denial  
**สิ่งที่ต้องปิดต่อ:** local account store ยังไม่พิสูจน์ named pilot allow-list และผู้ใช้หลายคนใน pool เดียวกันยังใช้ process/PVC เดียวกัน จึงยังไม่สามารถพิสูจน์ว่า user A เปิดข้อมูลของ user B ไม่ได้

### ผู้รับผิดชอบในแต่ละจุดควบคุม

| บทบาท | หน้าที่ |
|---|---|
| End user | เลือก environment ก่อน login และใช้งานเฉพาะข้อมูล/งานที่ได้รับอนุญาต; เปลี่ยน environment ต้อง logout และสร้าง session ใหม่ |
| Gateway | ยืนยันตัวตน, เก็บ environment preference, ออก session cookie และ route traffic; ไม่ mount workspace หรือ state ของ pool |
| Secure runtime | ประมวลผล protected data ผ่าน internal services; อ่าน approved package cache; ไม่มี public Internet egress |
| Internet runtime | ดาวน์โหลด dependency และทำงาน staging; ไม่เห็น Secure workspace/state และไม่สามารถ approve package ของตนเอง |
| Package approver | ตรวจ source, license/security result และ SHA-256; แก้ approval manifest และสั่ง resume promotion Job |
| RDT data owner | อนุมัติ scope ของ snapshot/view, field, retention และ named pilot users |
| Kubernetes/platform owner | จัดการ Secret, PVC, immutable image digest, NetworkPolicy, ingress, per-user runtime และ rollback |
| Security assessor | ตรวจ evidence ของ negative tests และยืนยัน acceptance ของ residual risk; ไม่อาศัยเพียง manifest apply หรือ pod Ready |

### เกณฑ์ปิดความเสี่ยงแบบตรวจรับได้

ความเสี่ยงทั้งสามข้อจะถือว่าปิดได้เมื่อมี evidence ครบดังนี้:

1. Secure outbound tests ไปหลาย external destinations ล้มเหลว ขณะที่ DNS และ internal LiteLLM ยังใช้งานได้
2. Active Secure model catalog และ runtime config ไม่มี external provider/fallback
3. RDT source mount/identity เป็น read-only และจำกัด scope; source-write และ out-of-scope-read tests ล้มเหลวจริง
4. Results folder เขียนได้และไม่ย้อนกลับไปแก้ source
5. Internet pod อ่าน Secure workspace/state/history/attachment ไม่ได้
6. Package ที่ไม่ได้ approve, hash ผิด หรือ path ไม่ปลอดภัย promote ไม่ได้
7. ปิด self-registration หรือ enforce approved pilot group
8. ผู้ใช้ A อ่าน แก้ไข หรือค้นหา file/report/session/attachment ของผู้ใช้ B ไม่ได้ผ่าน UI, API, terminal หรือ tool
9. ไม่มี anonymous report route, automatic publisher, external-export credential หรือ scheduled export สำหรับ pilot
10. Evidence ทุกชุดระบุ running image digest, test identity, environment, payload, expected result, actual result และวันเวลาทดสอบ

## 1. Prevent external leakage

### Required control

Block Internet access at the infrastructure layer for Harness and execution workers, allow only required internal services, and disable external model fallback. Confirm the rule through representative outbound-denial tests from each relevant environment.

### Current DSH implementation

- The login page defaults to the **Secure / Internal** execution pool, which is the Internet-Off option.
- `dsh-secure` has label `egress-mode=offline` and is selected by the `dsh-offline-egress` NetworkPolicy.
- The offline policy permits cluster DNS and the internal LiteLLM service on TCP port 4000 while denying general external egress.
- `dsh-internet` is a separately selected execution pool with general Internet egress.
- The two pools have separate writable workspaces, runtime state, session storage, attachments, and launch tokens.
- DSH's primary model route points to the internal LiteLLM service. The active repository configuration lists additional in-cluster models, but it also contains a `deepseek-official` provider entry. The network policy blocks that external route from Secure, but the catalog entry should be removed or disabled before claiming external fallback is disabled by configuration as well as by network enforcement.

### Evidence verified on 15 October 2026

| Evidence | Observed result |
|---|---|
| Production deployments | `dsh-environment-gateway`, `dsh-secure`, and `dsh-internet` each reported one Ready replica |
| Running image | All three deployments used immutable digest `sha256:d3a300605a87aa63ec4a2588f827658a132407ff17908ba49403fa7cca8d261a` |
| Network policies | `dsh-offline-egress`, `dsh-online-egress`, and `dsh-environment-pool-ingress` were present |
| Secure outbound test | HTTPS request to GitHub timed out after eight seconds and returned HTTP `000` |
| Internet outbound test | Equivalent request from `dsh-internet` returned HTTP `200` |
| Secure approved packages | `/packages/approved` is mounted read-only |
| Cross-environment mounts | Secure mounts `protected-workspace`; Internet mounts separate `staging`; neither runtime mounts the other's workspace |

### Assessment

**Substantially implemented, with one configuration-hardening gap.** Infrastructure-level Internet denial for the current Secure pod was directly observed. This is a restricted-egress environment rather than a strict air gap because it intentionally communicates with the gateway, cluster DNS, internal LiteLLM/GPU inference, Kubernetes storage, and other required cluster services.

Before pilot acceptance, remove or disable external provider entries and verify that the Secure catalog contains only approved internal endpoints. Repeat the denied-outbound test from every Secure execution image or worker introduced for the pilot.

## 2. Prevent damage or excessive access

### Required control

Run generated code under a dedicated non-admin identity, expose only a limited read-only RDT snapshot or view, allow writes only to a separate working folder, and demonstrate that source modification and out-of-scope reads fail.

### Current DSH implementation

- Both DSH pools run as Linux UID/GID `10001` with `runAsNonRoot=true`.
- Privilege escalation is disabled and all Linux capabilities are dropped.
- Each runtime is limited to 4 CPU and 8 GiB memory.
- The Secure and Internet pools cannot mount each other's workspace or runtime-state volumes.
- Internet downloads dependency candidates only into `/packages/incoming`.
- A controlled promotion process checks approved paths and SHA-256 values before writing mode `0444` artifacts to `/packages/approved`; Secure mounts this cache read-only and installs in offline mode.

### Evidence verified on 15 October 2026

| Evidence | Observed result |
|---|---|
| Container identity | Both pools reported `runAsNonRoot=true`, UID `10001` |
| Privilege control | `allowPrivilegeEscalation=false`; dropped capabilities `ALL` |
| Protected dependency cache | Secure mount `/packages/approved` reported read-only |
| Environment workspace separation | Secure and Internet use different writable workspace volumes |

### Material gap

The protected Secure workspace is writable, and the current manifests do not identify a dedicated RDT data source mounted as a limited read-only snapshot or view. No current evidence demonstrates that:

- an RDT-specific service account or database identity has only the approved read scope;
- source RDT modification attempts fail;
- paths, databases, services, or data outside the approved RDT scope cannot be read; or
- generated outputs are restricted to a designated working-results folder.

### Assessment

**Partially implemented.** Runtime privilege reduction and environment separation are operating, but they do not replace data-level authorization. This control cannot be marked complete until an approved RDT snapshot/view and identity are configured and negative tests prove that source writes and out-of-scope reads fail.

## 3. Keep results contained

### Required control

Restrict the pilot to named users, require authentication for reports and working files, prevent automatic publication or external export, and demonstrate that an unauthorized user cannot open another user's reports or files.

### Current DSH implementation

- Public entry is through the authenticated environment gateway.
- The gateway does not mount either execution workspace or DSH runtime-state volume.
- Sessions are pinned to the selected Secure or Internet pool.
- Secure and Internet histories, attachments, runtime state, and writable workspaces remain separate.
- Moving project or application data between environments requires a separate operator-approved copy; environment selection does not automatically copy data.
- External export from Secure is blocked by the observed egress policy.

### Material gap

The current gateway has a persistent local credential store and permits account creation. It is not yet proven to enforce a closed list of named pilot users through corporate identity or an approved account-administration process.

More critically, multiple authenticated users selecting the same environment share that pool's DSH process and mounted workspace/state. User-labelled directories do not provide a security boundary when users can run shell commands and generated code. Therefore, the required negative test—one authenticated but unauthorized user being unable to open another user's reports or working files—cannot currently be expected to pass reliably.

### Assessment

**Not complete.** Authentication and cross-environment containment exist, but named-user enforcement and per-user report/workspace isolation are insufficient for mutually untrusted pilot users.

## Required actions before calling all three controls complete

1. Remove external model/provider routes from the Secure catalog and verify only approved internal endpoints are reachable.
2. Provision a dedicated RDT pilot identity with read-only access to an approved, limited snapshot or database view.
3. Mount or expose RDT source data read-only and provide a distinct writable results directory.
4. Execute and retain negative tests for source modification and reads outside the approved RDT scope.
5. Disable public self-registration for the pilot or restrict it to an approved named-user list backed by the approved identity process.
6. Provide one DSH pod plus workspace/state PVC per pilot identity, or introduce an equivalently tested sandbox and access-control layer.
7. Verify that pilot user A cannot list, read, modify, or retrieve user B's workspace, report, attachment, and chat-session content.
8. Verify that reports require authentication and that no scheduled or automatic publication/export route is enabled.

## Pilot decision statement

The current DSH deployment already limits Internet leakage from its default Secure environment and separates Secure execution from Internet-enabled dependency preparation. It also reduces container privilege. It does not yet limit RDT access to a verified read-only data scope or contain reports and working files between authenticated users in the same pool. The three-control RDT pilot gate is therefore **partially satisfied and not yet ready to be recorded as fully closed**.

