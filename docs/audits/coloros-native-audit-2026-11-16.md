# ColorOS 17 on the Galaxy S25 Ultra: what keeps it from feeling native (read-only audit)

The audit is interim. The owner asked for the report before the work was done. Everything below comes from reading the code and logs. Nothing was built, changed or tried on a phone.

Sources:
- Code: /home/user/oneos-test/switcher/assets (working tree, read only)
- Newest session: scratchpad/log8/oneos-logs-bceaef29fb128e94 (app 0.5.16, Full logs off, charging, no logcat)
- Previous session: scratchpad/log7/x/oneos-logs-4d2e95c67f065941 (app 0.5.13, Full logs on). I merged its five logcat files into scratchpad/audit/l7.log and cut the guest part into guest7.log. **The logcat has a gap from 03:06 to 03:08** because rotated files were dropped. The only post-boot "steady" window is 03:05:15 to 03:05:55, saved as audit/steady.log.

The guest image itself was not available, so every claim about what is inside ColorOS is inferred.

---

## Status (updated 2026-11-16, after sessions bceaef29fb128e94 and c2d30e95cde9775b)

Done or learned (do not plan again):
- **Guest baseline 16 s -> under 1 s** (c9e13b9, DeathThoughts/OneOS-test PR #1). Tried on the phone, bceaef29fb128e94.
- **CPU heat cap needs three readings** (91a68d9, PR #2). Tried on the phone, c2d30e95cde9775b: 16 spikes held back. Level 3 still came twice, on zones at 100-106 C for 30 s while Samsung's AP read 48-51 C. Basing the CPU rule on AP was proposed to the rule's owner; not done.
- **Preflight timing** (bd980c5, PR #2). Tried on the phone, c2d30e95cde9775b: of the 15 s before "switch start", 9 s are the libtimer.so readlink scan (one fork per process) and 2 s are the files.sha256 hash (62 files, 819 MB). The hash is not the cost. The scan fix is in progress on branch fix/fp-icon-and-libtimer.
- **Fork counter in the sampler** (d58d388, PR #2). Tried on the phone, c2d30e95cde9775b: 167-469 forks/s (10,000-28,000 a minute) all session, which confirms the size of finding 1's fork budget. Forks alone do not explain the sys CPU: at 05:58:12, 167 forks/s came with 28% sys.
- **Heat of session bceaef29fb128e94** was mostly the phone charging (owner's condition). Unplugged, c2d30e95cde9775b peaked at 42.6 C skin, against 46.1 C.
- **ColorOS fingerprint icon too low** (owner, c2d30e95cde9775b): the icon dpi was taken from a shell virtual display (329 dpi) instead of the panel (501.04). The fix is in progress on branch fix/fp-icon-and-libtimer.

Not started (owner: leave as it is for now): findings 1-10 below, unchanged.

---

## 1. Top opportunities, ranked by gain, effort and risk

| # | What | Gain | Effort | Risk |
|---|---|---|---|---|
| 1 | **The guest's app-storage loop runs about 2,440 `stat` programs every 10 s** (ensure_app_storage.sh, about 488 packages × 5 folders). That is about 14,600 program starts a minute, all session. | Probably most of the known "150-300% sys CPU while idle". Idle CPU, heat and battery. | S | Low |
| 2 | **The guest's shared storage is chowned recursively twice on every switch.** guest_prepare.sh:5090 sets all of /data/media to 1023 with `chown -R`. The guest loop then puts back 1464 app folders with `chown -R` ("realigned 1464" in every session). | Switch time and I/O, growing with the user's files. Apps' external folders have the wrong owner for about 70 s after boot. | S | Low |
| 3 | **Prebuilt app code goes unused.** The patched framework.jar is on the boot class path, so the boot image is rebuilt by odrefresh, and the image's own compiled app files (odex) no longer match. Apps fall back to `verify` (interpreter + JIT). Settings is `status=verify reason=vdex`. The launcher was `verify` before OneOS's compile script ran. | App launch speed and smoothness for every ColorOS app that OneOS does not compile itself. | S-M (extend the existing compile script) | Low |
| 4 | **SystemUI is restarted in every session** at the first screen-off, for the wallpaper AOD feature (panoramic_aod.log: log7 03:05:51, log8 05:19:16). Until then, `dumpsys power` runs every 5 s. | Saves one SystemUI cold start per session (168 threads) and the polling. | M (feature must be present before boot) | Low-M |
| 5 | **Diagnostics run during boot cost real CPU and freeze UI.** The 20 s round took 45 s (log8) and pushed the 40 s round out. Each round forks one `cat` per thread in the whole system. The 90 s round takes Java and native stack dumps of SystemUI and the launcher (1.77 MB and 1.42 MB native dumps), which stops every one of their threads. These rounds run even with Full logs off. | Smoother first 2-3 minutes, fewer hitches. | S | Low |
| 6 | **A "service stopper" loop on the host runs every 0.2 s, calling `getprop` 9 times each pass.** That is about 2,700 program starts a minute and 5 wakeups a second. | About 5-10% of a core, plus deep-idle time. | M (small native helper that waits on properties) | Low-M |
| 7 | **Network watching polls every 10 s, twice** (host net_watch and the guest loop), plus an APEX check that runs a `cat` per loop device. About 1,300 program starts a minute. | CPU, and faster network repair if it becomes event-driven. | S-M (`ip monitor`, or a netlink listener) | Low |
| 8 | **The auto-return watcher dumps the whole main log buffer every 10 s** (`logcat -d -b main -s SurfaceFlinger`). The 90 s round does about 7 more full dumps. Sampler log8 05:19:58: logd at 93% and logcat at 66% of a core, right after the 90 s round at 05:19:50. | logd load. | S | Low |
| 9 | **The panel-fit loop calls `wm size` through nsenter every 0.5 s during boot** for about 2.5 min (about 300 calls, about 2,500 program starts) while the guest is booting. | Less contention during boot. | S | Low |
| 10 | **ColorOS's app freezer (Hans) is disabled** ("cgroup.freeze not present", "SceneManager hans disabled", "... when hans disable"). No `am_freeze` was seen in the visible guest window; One UI logged 62 before the switch. | Possibly large idle-battery gain. **Inferred**: the path Hans checks is not known yet. | M (investigate first) | M |

Also worth an owner decision: while the heat cap holds any level, the WALT touch boost is switched off. In log8 that was about 2.3 of 3.7 minutes. Even at level 1-2, the boost frequency (1.79 / 2.25 GHz) is below the cap.

---

## 2. Findings with evidence

Status is P (proven from code or log) or I (inferred). "Phone?" means a phone test is needed to confirm.

### Program-start (fork/exec) budget

These are estimates from the code, for steady state after boot.

| Watcher | Code | Period | Program starts per minute (est.) |
|---|---|---|---|
| ensure_app_storage via app_storage_loop (guest) | guest_prepare.sh:5761-5822, 5941-5964; started guest_start.sh:1585 | 10 s | **~14,600** (488 pkgs × 5 `stat`) |
| Service stopper (host) | oneos_switch.sh:1458 | 0.2 s | **~2,700** (+300 if `sleep` forks) |
| net_watch + apex_watch (host) | oneos_switch.sh:1586-1609 | 10 s + ping up to 2 s | ~1,000-1,200 (net_fix ~30, ip/awk/ping ~12, ~54+ loop `cat` + basename/dirname) |
| net_fix inside the guest loop (duplicate) | guest_prepare.sh:5949 | 10 s | ~180 |
| dt2w keeper (guest) | guest_start.sh:2181-2281 | 0.1 s | builtins; ~75 `cat`; 600 if `sleep` forks; 600 wakeups/min even with the screen off |
| Watchdog feeder | guest_prepare.sh:218-256 | 2 s | ~150-240 |
| Call-audio watcher (guest) | guest_start.sh:1508-1545 | 2 s | ~150, plus 30 `dumpsys telephony.registry` per min |
| Auto-return (host) | oneos_switch.sh:4252-4664 | 1 s / 10 s | ~130, plus 6 full main-buffer dumps per min |
| Heat cap | oneos_switch.sh:3819-3885 | 10 s | ~60, plus 6 Java dumps (thermalservice) per min |
| Sampler | oneos_switch.sh:3646-3672 | 30 s | ~70, plus `dumpsys window windows` (takes the WM lock) and `dumpsys thermalservice` |
| Audio keeper (guest) | guest_start.sh:1237, 1301 | 3 s | ~40 |
| Others: adb watchdog 10 s, ims 60 s, charge 60 s, A2DP 10 s, panel keeper 15 s, UI activator 2 s, boost 1 s | | | ~150 together |
| **Total** | | | **≈ 19,000-20,000 per minute; ~75% is ensure_app_storage** |

### All findings

| ID | Area | Evidence | Cause | Proposed change | Gain | Effort | Risk | Phone? |
|---|---|---|---|---|---|---|---|---|
| F1 | Host and guest watchers | Code above. Package count: ui_activator.log "488 profile dirs"; app_storage.log "realigned 1464" (= 3 × 488). Sampler log8: sys 181/303/377/75/239/203/183/43% against user 48-332%, and the per-process list holds no big process. That fits short-lived processes. Samsung's integrity checker on program start shows up in top (`kworker five_wq`, log8 05:18:59 and 05:20:28; log7 03:06:49). | P (code); I (share of sys CPU) | Run ensure_app_storage only when the packages.list md5 changes (the loop already computes it), plus once after boot. Do the check in one program (`find ... -maxdepth 1 -printf '%U %p'`) instead of one `stat` per folder. | −0.5 to 1+ core of sys CPU (I) | S | Low | Yes (fork counter) |
| F2 | Storage ownership | guest_prepare.sh:5090-5092 (`chown -h -R 1023:1023` and `chcon -R` of the whole /data/media). The guest loop realigns 1464 folders with `chown -R` (guest_prepare.sh:5788-5795). app_storage.log: 21:32:39, 01:23:33, 02:50:33, 03:05:32, 05:18:22. | P | Chown only the top-level folders, without -R; leave Android/{data,media,obb}/* alone, or do it once with a marker. | Switch seconds (grows with the user's files), no I/O burst after boot, correct external folders from the start | S | Low (keep -h) | Yes (time the 5c step) |
| F3 | Compiled code | log8 diag_90_dexopt.txt: Settings `[status=verify] [reason=vdex]` from `/system/system_ext/priv-app/Settings/oat/arm64/Settings.vdex`. sysui_compile.log: "launcher arm64 is verify" before the script compiled it. takeover.log: odrefresh "93 files in /data/misc/apexdata/.../dalvik-cache/arm64". Stack traces point into the apexdata boot.vdex. Boot class path jars are patched: framework_patched, oplus-framework_patched, telephony-common_patched. | I (strong): the prebuilt odex is rejected after the boot image changes. Not proven that the image ships an odex. | Extend oneos_sysui_compile.sh to a list of the most-used apps (Settings, Phone/Contacts, Messages, Gallery, Files, Clock, Weather, Browser, Theme store) with `-m speed` (or speed-profile once profiles exist). Gate it as today (thermal, marker per boot image). Optionally run `cmd package bg-dexopt-job` once per boot image while charging with the screen off. | Faster cold launches, less JIT CPU (typically 20-40%, not measured) | S-M | Low | Yes (`am start -W`) |
| F4 | SystemUI restart | guest_prepare.sh:3040-3062: runtime `content insert` into AppFeatureProvider, then `kill -TERM` SystemUI at screen-off, polling `dumpsys power` every 5 s, up to 2 h. Logs: "feature added" in both sessions. log7 03:05:51.963 "Process 10633 exited due to signal 15", restarted as 6090. | P | Put com.oplus.systemui.panoramic_aod.enable into the image's app-feature XML before boot (it is bind-mounted the same way as the other feature switches), so SystemUI starts with it. Drop the restart and the poll. | One SystemUI cold start less per session, plus polling | M (need the image's feature XML format) | Low-M | Yes |
| F5 | Diag rounds | oneos_switch.sh:4459-4467: one `cat` per thread in /proc. 4476-4482: `debuggerd -j` and `debuggerd` on SystemUI and the launcher. 4521: `getevent -lt` on the touchscreen for 15 s (touch_events.txt is 0 bytes). `ls -l /proc/*/fd/*`. Several `logcat -d`. auto_return.log log8: diag_20 started about 05:17:20, saved 05:18:05; "40 skipped". log7: 03:04:34 to 03:05:14. Rounds run with Full logs off (log8 has diag_90 stack and native files). | P | Read thread names with the shell's own `read`. Do stack dumps, the fd scan and getevent only with Full logs on or when Home failed. Log each round's start and end time. | Fewer boot hitches; less boot contention | S | Low | Yes |
| F6 | Service stopper | oneos_switch.sh:1458: 9 `getprop` per 0.2 s. The return stops it by `pkill -f "ctl.stop zygote"` (return_to_oneui.sh:260, 697). | P | Native helper (native/build.sh exists) using `__system_property_wait`. Keep "ctl.stop zygote" in its command line so the return path stays unchanged. | ~5-10% of a core, 300 wakeups/min | M | Low-M (zygote protection; socket binds stay as a second guard) | Yes |
| F7 | Network watch | oneos_switch.sh:1586-1609 and guest_prepare.sh:5949 (net_fix twice per 10 s). apex_watch.log: 338 rounds, about 33 lines each (the dm-verity check from older reports). | P | One copy of net_fix, driven by `ip monitor link address route rule` with a debounce. APEX check every few minutes, with builtins. | ~1,300 starts/min; network repaired in ms instead of up to 10 s | S-M | Low | Yes |
| F8 | logd load | oneos_switch.sh:4639 (`logcat -d -b main -s SurfaceFlinger` every 10 s). Diag `logcat -d` calls at 4456, 4512-4513, 4571-4573. Sampler log8 05:19:58 "93.3 logd 66.6 logcat". log7 volume with Full logs: 70,596 lines in 40 s (~106k lines/min, 37,793 of them D). The quiet W level is already the default (guest_props.sh:196-280). | P | Use `--pid=<sf pid> -T <last time>` (logd skips other pids server-side), or stop the check once Home is up and composition is confirmed. | logd CPU | S | Low | Yes |
| F9 | Panel fit during boot | oneos_switch.sh:2055-2078: every 0.5 s until 120 s after the first answer. Runs on S25U ColorOS (phone form, hole property set). | P | Wait for the window manager answer or boot completion, then check on change only. | ~2,500 starts during boot | S | Low | No |
| F10 | Hans freezer | guest7.log: "OplusHansManager : cgroup.freeze not present" 03:04:50.520; "SceneManager hans disabled"; 260 × "not ready"; "... when hans disable". 0 `am_freeze` in 03:04-03:10 (the window has a gap). AOSP "Freezer enabled" 03:04:38. | I | Find which path Hans checks (image's oplus-services.jar). If it is a ColorOS-only cgroup, create it from OneOS for the session and remove it at the return. | Idle battery (possibly large) | M | M | Yes |
| F11 | Boost versus heat cap | boost.log log8: the kernel input boost is off 05:17:19-29, 05:17:50-18:50, 05:19:21-end. heat_cap.log: levels 1-3. Code oneos_switch.sh:4128-4135. | P | Owner's call: keep the WALT input boost at levels 1-2 (its frequency is under the cap anyway). | Touch response while warm | S | Low (heat) | Yes |
| F12 | Sampler / heat cap | `dumpsys window windows` every 30 s (WM lock). `dumpsys thermalservice` both every 30 s and every 10 s. | P (cost), I (jank) | The heat cap writes skin temperature to a file and the sampler reads it. Read blur state only in diag rounds. | Small; may remove a 30 s hitch | S | Low | Yes |
| F13 | dt2w 10 Hz | guest_start.sh:2280 `sleep 0.1` all session, screen off included. | P | Use the existing screen-state events reader to poll fast only around wake; 1-2 Hz while asleep. | Screen-off wakeups | M | M (dt2w timing) | Yes |
| F14 | Call-audio watcher | guest_start.sh:1508-1545: `dumpsys telephony.registry` every 2 s. | P | Slow to 10 s when idle, or trigger on call-state events. | Small | S | Low | No |
| F15 | Boot path timing | log7: app tap 03:02:58 → switch 03:03:13 → takeover 03:04:05 → zygote 03:04:27 → enable_screen 03:04:50. Android's own boot is 23 s; OneOS adds 15 + 52 + 22 s. log8: guest_prepare 05:16:22→05:16:44, guest_start 05:16:48→05:17:09 (SF released 05:16:58). | P | Add timestamps to the "[Pivoted Root]" lines; then target the largest steps. The 15 s is already known. | Seconds of switch time | S (measure) | Low | Yes |
| F16 | Process start at boot | guest7: 550 "Slow operation" lines, startProcess p50 187 ms, p90 589 ms, max 825 ms, 03:04:40-03:05:10. 35 skipped-frame events in the same window, 1 later. | P (symptom); I (cause: contention from F1/F5/F9 plus the boot burst) | Comes from fixing F1, F5 and F9. | Faster first minute | — | — | Yes |
| F17 | Frame pacing | diag SF: missed frames 19 at 20 s → 2016 at 90 s (HWC 1727, GPU 605) in log8; log7 10 → 2509. composition=DEVICE; 0 composer rejections. | P (counts); I (mostly boot) | Capture missed-frame deltas over steady state (90 s → return) before acting. | Unknown | — | — | Yes |
| F18 | Refresh policy | diag_90 SF: displayManagerPolicy fixed at 120-120 Hz, IdleFps:-1, KernelIdleTimer=false. vrr_lfd in the guest diag is cut at 600 characters, so its "[result]" is missing. One UI showed "LFD freq 10-60hz" with no clients set. | I | Measure the panel's low-frequency drive while idle in the guest before planning. | Idle battery (maybe) | S (measure) | — | Yes |
| F19 | OneOS guest app | Sampler log7 03:09:19: com.fahadali.oneos.guest at 171% during its cold start. | I | Ship it compiled or with a baseline profile. | Small | S | Low | No |
| F20 | Owner settings and conditions | Charging in log8 (charge_watch "Charging PDIC"). Skin 44-46 C → thermal status 3, app compile postponed (sysui_compile.log 05:19:21), heat-cap levels. CPU-Z in the foreground (vrr "CurrPkgName: com.cpuid.cpu_z"). Power saving 0 in log8. | P | Report only. Ask for one session unplugged with the screen off. | — | — | — | — |

---

## 3. Native-code candidates

1. **Property stopper (F6).** About 80 lines of C in switcher/native. It looks up init.svc.{zygote, zygote_secondary, surfaceflinger, bootanim, audioserver, dumpstate…}, blocks in `__system_property_wait`, and on a change to "running" sets ctl.stop <svc>. It honours the same flag files (guest_audio.flag, oneos_host_sf_frozen; one stat per wake). Its argv contains "ctl.stop zygote", so the return's pkill still matches. **Better than shell:** no CPU and no wakeups when idle, and it reacts in microseconds instead of up to 0.2 s. **Worth it:** yes. Risk is low because the socket binds still protect the guest zygote.
2. **Net watcher (F7).** An rtnetlink socket subscribed to link, IPv4 address, route and rule groups, which runs net_fix.sh debounced by 500 ms. The shell version `ip monitor … | while read` gets most of the gain without new native code. **Worth it:** yes, shell first.
3. **Unified host monitor `oneosd`** (auto-return, panel keeper, heat cap, boost main loop, sampler). Uses inotify on the return-request file, a property wait on oneos.guest.powerctl, and timers with file descriptors opened once. **Gain:** a few hundred starts a minute and less latency; smaller than F1/F2/F6. **Cost:** L, and it touches the return path. **Worth it:** later, after F1-F9.
4. **Stub HALs for missing OPPO HALs: not proposed.** These are dead ends per CLAUDE.md. A stub would only silence retries (OplusWifiHal ~240 lines/min, urcc ~130/min). It would need a VINTF change on Samsung's side, and how the callers behave is unknown.
5. **Native touch boost: not needed.** The WALT kernel input boost is already used, with no process per touch. An app-launch boost (WALT sched_boost or top-app uclamp on launch events) is possible from OneOS's side but unmeasured. The guest's hints do reach Samsung's HyPer HAL (guest7: 255 UCLAMP_MIN_BOOST and 180 TID_LOW_LATENCY requests from guest TIDs).

---

## 4. Dead ends found (candidates for CLAUDE.md's list)

- **`OplusWifiHalService: Can't call executeDriverCommandWithResult: mIOplusWifiHalService is null`**: about 240 per minute from system_server (guest7: 268 in ~130 s; steady.log: 160 in 40 s). It needs OPPO's vendor Wi-Fi HAL.
- **Missing OPPO additions to ART**: `VMRuntime.SupressionGC` (154 lines, one per process start: "export/Mainline has no Oplus natives"), `VMRuntime.updateProcessValue` (152), `setOplusAppLaunchOptFlags` (150). This is the image's own export ART module (inferred: the same on a real IN Find X9 Ultra). Not a Samsung or OneOS issue.
- **OplusCpuLimitManager**: `/dev/cpuset/l-background`, `h-background` and `kswapd-like` give ENOENT. Those are OPPO kernel cpusets; do not create them on One UI's cgroups.
- **OplusStorageManagerFeature `writeF2fsRelatedNode` EACCES** (~54 stack traces/min). ColorOS is trying to retune Samsung's f2fs. Leave it alone; letting it through would change One UI's storage behaviour.
- **libprocessgroup "Unknown profile action: SetClamps", "unknown attribute CfqWeight/BfqWeight/GpisSfCpuset", "JoinCgroup: controller schedtune is not found"**: a mismatch between the guest's libprocessgroup and Samsung's vendor task profiles. Few lines, at boot. Probably harmless (inferred).
- **`minksocket: MinkIPC ERROR … Client down`**: host vendor daemon pid 1920, in bursts at the framework stop and the return (1190 and 1480 per minute at 03:03-03:04), and during face unlock. A side effect of killing processes. Harmless.
- **HYPER-HAL `set_uclamp_min(): sched_setattr failed … err = -1`**: 70 failures against 255 requests. Inside Samsung's HAL. Harmless (inferred).
- **com.oplus.blur screen capture** (captureLayers about 5 per second while the notification shade or keyguard is open; 274 from pid 11498): this is ColorOS's own blur design, not a fallback (inferred).
- **ColorOS `DynamicFramerate … LP_SUPPORT … not enabled`** (one per process) and `OplusDynamicFrameRateRUS notifyThermalBroadCast: failed` (151): probably tied to OPPO's display or thermal HAL. **Unverified:** needs the image's oplus-framework.

---

## 5. Measurements for the next phone session

- **Fork rate:** read `/proc/stat` "processes" in each sampler line, using the shell's `read`.
- **Per-watcher CPU:** at the return, record `/proc/<pid>/stat` fields utime, stime, cutime and cstime of each watcher's shell.
- **Log volume:** `logcat -g` (buffer sizes) and `logcat -S` (lines per process) at 90 s and at the return.
- **Compiled state:**
  - `pm art dump | grep -o 'status=[a-z-]*' | sort | uniq -c`
  - `ls /system/system_ext/priv-app/Settings/oat/arm64/`
  - `ls /data/misc/apexdata/com.android.art/dalvik-cache/arm64 | grep -E 'services|oplus'`
  - `am start -W` TotalTime for Settings, Gallery and Contacts, before and after compiling them.
- **Hans:**
  - `ls -d /sys/fs/cgroup/cgroup.freeze /sys/fs/cgroup/apps/cgroup.freeze /sys/fs/cgroup/frozen 2>&1`
  - `cat /sys/fs/cgroup/apps/uid_*/pid_*/cgroup.freeze | sort | uniq -c` after 5 min with the screen off
  - The Hans freeze-path strings from the image's oplus-services.jar.
- **Timing:** timestamps on every "[Pivoted Root]" line in takeover.log, and start and end times of each diag round.
- **Steady-state frames:** SurfaceFlinger missed-frame counts at 90 s and at the return (add an SF dump to the return diag); `dumpsys gfxinfo com.android.launcher framestats`.
- **Panel:** the full vrr_lfd readout (do not cut at 600 characters), while idle on the home screen in the guest.
- **Thread count:** `ls -d /proc/[0-9]*/task/* | wc -l`.
- **Whether busybox `sleep` starts a new process:** run 100 sleeps and compare the "processes" counter before and after.
- **Idle battery:** one session unplugged with the screen off for 10 min (charge_watch current), with the owner's charging and CPU-Z left out.
- **App-launch boost:** whether the guest sends a LAUNCH power mode to Samsung's power HAL. Look at the HYPER-HAL lines around an `am start`.

---

## A. What was checked

- **Code:** oneos_switch.sh, the guest_prepare.sh sections, guest_start.sh sections, guest_props.sh (log level), boot_status.sh. Specifically: all session loops (1040-1130, 1458, 1586-1609, 2022-2075, 2160-2200, 3590-3672, 3790-3890, 3895-4140, 4160-4245, 4252-4664), the dt2w and audio watchers (guest_start 825-860, 1115-1140, 1195-1225, 1237-1345, 1500-1545, 1595-1665, 1977-2281), net_fix/ensure_app_storage/app_storage_loop (guest_prepare 5761-5966), watchdog feeder (200-258), /data/media chown (5070-5095), panoramic AOD (3005-3075).
- **Logs:** log8 stage/, guest/, host/ and diag/ (frames, composition, surfaceflinger, vrr, panel_refresh, dexopt, thermal, throttle, stack/native sizes); log7 stage/ and the merged logcat: tag volume, E/W ranking, cgroup, HYPER-HAL, Hans/freezer, lmkd, ART/dexopt, launch times, crashes, SystemUI restart, blur.

## B. Findings so far

Sections 1 and 2 are the full ranked list. In order of expected gain: F1, F2, F3, F5, F4, F6, F10, F7, F8, F9, then F11-F19. Each is marked P or I in its row.

## C. Still to do (next steps)

- **Memory:** the zram, swappiness and psi settings were not read. Samsung lmkd's 4 reclaims at boot ("filecache is low (6193688kB)", guest7 03:04:57-03:05:06) are not explained yet. Athena/FCA was barely looked at (0 "Reclamation" lines).
- **Rendering details:** RenderEngine backend in the guest SF dump, layers.txt and composition per layer, blur state from diag_series.txt over the session.
- **Older sessions** log1 to log6 were not read; use them to check repeatability (missed frames, realign counts).
- **guest_start before zygote** (05:16:48 → 05:17:09): needs timestamps; read guest_start.sh lines 140-700 for waits.
- **The 15 s before the switch** is already known and was not re-checked.
- **Steady state:** the logcat gap at 03:06-03:08 means there is no steady-state error rate beyond 40 s. A full-log session that lasts 5+ minutes is needed, with Full logs on but a larger rotation.
- **Image-only items:** confirm F3 (whether the odex is present in the image), F4 (app-feature XML format, e.g. under my_product/etc/extension), F10 (Hans path), and LP_SUPPORT. Each needs the coloros17-findx9u-in-1105 image to read.
