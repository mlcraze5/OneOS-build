# Working rules for this fork

Standing rules from the fork's owner. They apply to every session.

## Roles

- The main session plans, investigates, reviews and orchestrates. It does not
  write the code changes itself.
- Every actual code change is implemented by an Opus 5.5 subagent, briefed with
  a self-contained task; the main session reviews the result before it is
  committed.

## Biometrics in the guest (fingerprint and face)

- Enrollment happens in One UI only. The guest never enrolls a fingerprint or a
  face of its own, and nothing is added that makes it able to.
- The guest recognises the enrollments One UI already has: guest_prepare.sh
  carries One UI's enrollment metadata across on every switch, the templates
  stay in the phone's TEE, and the guest unlocks with them through the phone's
  own HAL.
- Safety comes first. Nothing of One UI's credentials (PIN, gatekeeper handle,
  synthetic-password blobs) is read or written. Host-side writes into the
  guest's data go through the no_symlink guard. A biometric path that fails
  must fall back to the guest's PIN, and no change may be able to lock the
  owner out of One UI.
- A change is not called working until it was tried on a phone; say plainly
  what was only read or only built.

## Performance

- Native code, not interpreted: a patched APK or jar should run compiled
  (dex2oat / odex for the patched file) instead of falling back to the
  interpreter or JIT because its oat was hidden.
- Use the GPU where the work is rendering or model inference.
- HyperOS and ColorOS are the guests that matter most for this.

## Repository

- Work lands in this fork, never in vdcoolok/OneOS or its upstream.
- Follow the repository's own style: comments say why and name the phone or
  report the fix came from; one logical change per commit.

## Research before planning a fix

Owner's rule (2026-11-16, after the ORMS screen-on boost was planned as a P1
task and turned out impossible on Samsung). Before a problem becomes a task,
and before any subagent is briefed:

- Trace the whole dependency chain of the thing to fix: which service, HAL,
  kernel node or vendor binary it ends in, and whether the Samsung host has it.
  A guest feature that needs an OPPO, Xiaomi or Google vendor HAL or kernel
  driver cannot be fixed from the guest's side.
- Prove it from the log first: the exact failing line, how often, and when.
  Say plainly what was only inferred (for example, the guest image was not
  available to read).
- Separate the owner's own settings (One UI or guest settings) from OneOS
  bugs; settings are reported, not "fixed" in code.
- Check this list of known dead ends and add to it whenever a new one is
  found.

### Known dead ends (do not plan these again)

- ColorOS ORMS / screen-on CPU boost: ScreenOnCpuBoostHelper tries "orms core
  service" (`Orms_ManagerInner: cannot connect to orms core service!`), then
  UAH `urcc` (`Urcc is not declared`). Both are OPPO vendor-side; Samsung has
  neither (session 25b4785c4206828f). Any boost must come from OneOS's side
  (kernel nodes or Samsung's HYPER-HAL), measured first.
- Other OPPO vendor HALs missing on Samsung, same reason:
  `vendor.oplus.hardware.performance.IPerformance` (audioserver retries every
  5 s, AudioBoost rt boost ret -1), `cryptoeng.ICryptoeng` (system_server main
  thread waits 5 s at boot), `touch.IOplusTouch`, `displaypanelfeature`,
  `mmdisplayfeature`, `rpmh`, `charger`.
- CPU held at about 2.4 GHz all session: One UI's power saving
  (`settings global low_power=1`) sets `cpufreq_max_limit`; the heat cap
  respects it on purpose. Owner's setting, not a bug. One UI's framework
  stops for the guest, but the limit it wrote stays in the kernel; with power
  saving off the heat cap clears One UI's leftover limit and the guest runs at
  full clock (session 4d2e95c67f065941: 2246400 -> -1, 3.53/4.47 GHz).
- Samsung's lazy artd started by init during a guest session aborts with
  `Got callback on service which we did not register: ...IArtd`; the guest's
  own artd serves the compiles. Seen in every session, harmless.
- ColorOS face unlock that needs a swipe: the guest's
  `oplus_customize_face_unlock_remain_unlock_switch` (stay on lock screen) is
  on. Owner's setting.
- Face match time (0.8-2 s): Samsung's face HAL loads its TA on every
  authenticate (about 0.35 s) and needs several frames in low light. Inside
  Samsung's HAL; not touched.
