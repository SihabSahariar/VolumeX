# VolumeX — Product & System Architecture Plan

**Status:** v0.1 built · 2026-10-01 · "VolumeX" is a working name (see the naming risk in §10) · what was built, and how it differs from this plan: §13

---

## 0. Summary

- **What it is.** A Windows 10/11 tray app that makes one app, or the whole PC, louder than 100% without distortion. It also remembers each app's level, which Windows doesn't do reliably.
- **Why it wins.**
  - No desktop tool today boosts individual apps above 100%. EarTrumpet users have asked for it, and FxSound staff said in 2025 that FxSound can't do it.
  - We add the things competitors get wrong: per-app levels that stick, an always-on distortion guard, automatic rules, no device hijacking, and self-repair after sleep, Bluetooth changes and Windows updates.
- **How it works.**
  - Windows rejects any volume above 100%, so a boost means multiplying the audio samples ourselves.
  - Apps that need a boost are routed to a silent VolumeX virtual device, the **Boost Bus**.
  - A small native engine captures the bus, applies gain and a limiter, and plays the result on the real speakers.
  - Each app's own boost comes from Windows' per-app volume (the **ratio trick**, §3), so there is only one audio path.
- **What it costs the user.** Nothing when nothing is boosted. Apps at or below 100% never touch our code path, and the engine sleeps.
- **Stack.**
  - **Python 3.11 + PyQt5** for everything the user sees and all control logic.
  - **A small C++ engine** for the real-time audio loop.
  - **A signed virtual audio driver** for the bus device.
  - Python never touches audio samples in production.
- **Ship order.**
  - Phase 1 ships a driver-free "smart mixer" (per-app memory, rules, hotkeys, tray flyout).
  - In parallel we build the engine and get the driver signed.
  - Phase 2 adds boosting.

---

## 1. Product

### 1.1 The problem and the gap

Windows volume stops at 100%: the endpoint and per-app volume APIs reject values above 1.0. Laptop speakers, Bluetooth headphones and quietly mastered videos are often too quiet even at maximum. Current tools each fail somewhere:

| Tool | Boost | Main shortcomings (from user reports) |
|---|---|---|
| Letasoft Sound Booster | 500%, system-wide only | Uses code injection, so BattlEye blocks it. Boost "runs away" into distortion. The trial cuts audio for 5 s every 5 min. Paid updates expire. |
| FxSound | System-wide only | Per-app is "not something FxSound can do". Loses the device after sleep; Bluetooth bugs. Takes over the default device. |
| Boom 3D | System + per-app | Breaks after Windows updates. Leaves its virtual device behind after uninstall. Bloat (radio, player). |
| EarTrumpet, Win 11 mixer, Volume², SoundVolumeView | 100% max | Can't go past 100%. Windows forgets per-app levels (90+ "same question" votes on Microsoft Q&A). |
| Equalizer APO + Peace | ~+20 dB preamp | Intimidating. Detaches after Windows 11 24H2 updates. No limiter. Each new device needs manual setup. |
| Voicemeeter, SteelSeries Sonar | Per channel | Complex routing. Hijack the default device. Crackling. Sonar needs an account and bundled software. |
| Volume Master (Chrome) | 600% | Browser tabs only. Forces a fullscreen blue bar. |

### 1.2 Target users

1. **Everyday listener.** Laptop speakers are too quiet for a video or call. Wants one big slider that goes past 100%.
2. **Bluetooth headphone user.** Too quiet even at 100%. Wants a boost that applies itself when the headphones connect.
3. **Multitasker, gamer or streamer.** Game too loud, Discord too quiet, music in between. Wants per-app levels that stick, without extra latency on the game.
4. **Power user.** Hotkeys, rules, scenes, command line.

### 1.3 Product principles

1. **One screen.** Everything is in a tray flyout. No config files, no routing diagrams, no jargon.
2. **Safe by default.**
   - The limiter ("Distortion Guard") is always on.
   - The boost zone is clearly marked.
   - The slider caps at 300% unless the user unlocks up to 500%.
   - Volume changes ramp smoothly, and a hearing-safety notice appears on first use of the boost zone.
3. **Pay only for what you use.** When nothing is above 100%, audio flows exactly as Windows would route it: zero added latency, zero CPU.
4. **Never break the user's audio.** Every change we make to Windows is recorded in a journal and undone on exit, crash or uninstall. Our device is never left as the default.
5. **No junk.** No account, no bundled apps, no telemetry unless the user opts in. A trial, if we have one, never degrades audio.
6. **No code injection.** Safe to use with game anti-cheat.

### 1.4 Feature set

**MVP (Phase 1 + Phase 2).** "Driver" means the feature needs the Boost Bus.

| # | Feature | What the user sees | Gap addressed | Driver? |
|---|---|---|---|---|
| F1 | **Per-app boost to 300% (500% unlockable)** | Every app has its own slider that continues past 100% into an amber boost zone | No desktop tool does this | Yes |
| F2 | **Master boost** | Master slider: 0–100% is normal Windows volume, above 100% is boost | Quiet laptop speakers | Yes |
| F3 | **Distortion Guard** | Always-on true-peak limiter with a small "guarding" indicator; % labels show dB on hover | Boosters distort | Yes |
| F4 | **Per-app volume memory** | Levels are re-applied every time an app starts, including after reboots | Windows forgets levels | No |
| F5 | **Tray flyout mixer** | Left-click the tray icon to get the mixer with live meters. Scroll over the icon to change master. | Buried Windows mixer | No |
| F6 | **Boost the app I'm using** | Hotkey Ctrl+Alt+↑/↓ changes the foreground app by ±10%, with a small on-screen display | Unique | Boost part only |
| F7 | **Per-device profiles** | "AirPods: master 180%" applies itself when the AirPods connect | Bluetooth too quiet | Yes |
| F8 | **Auto rules** | "When Zoom starts, set Spotify to 30%." "Always keep Chrome at 150%." | Settings that follow the app | Partly |
| F9 | **Survives sleep, hot-plug, Bluetooth and Windows updates** | Nothing to do; it just keeps working | FxSound/Boom/Equalizer APO complaints | Yes |
| F10 | **Reset audio (panic button)** | One click puts every Windows audio setting back as it was before VolumeX | Leftover devices, broken audio | Yes |
| F11 | **Three-step first run** | Welcome → install audio component (one UAC prompt) → "Can you hear this? Drag to boost" | Setup complexity | Yes |
| F12 | **Loudness Equalization toggle ("Quick boost")** | Offered only on drivers that support it (Phase 1 stop-gap) | Driver-free lift | No |

**Phase 3 — comfort**
- **Night mode / dialogue leveler.** A compressor on the bus that makes quiet dialogue louder and loud explosions and ads quieter.
- **Scenes.** "Movie", "Meeting", "Gaming" set many app levels at once. They can switch automatically by device or foreground app.
- **Auto-ducking.** When Discord, Teams or Zoom has voice activity, other apps drop by X dB. This is driven by per-app meters and needs no DSP.
- **Focus mode.** Background apps are lowered or muted when they lose focus.
- **Per-app output device.** For example, Discord to the headset and the game to the speakers. Uses the same routing API as the Boost Bus.
- **Quiet hours.** Caps maximum volume on a schedule.

**Phase 4 — advanced**
- **Isolated lanes.** Per-app EQ, per-app leveler, and a per-app limiter (§7).
- **Mic boost** through a VolumeX virtual microphone.
- **CLI and Stream Deck plugin.**
- **Optional zero-latency APO backend.**
- **Browser companion extension** for per-tab volume. Windows sees a browser as one app, so this can't be done at the OS level.

### 1.5 UX sketch (tray flyout)

```
┌────────────────────────────────────────────────────┐
│ VolumeX              🔊 Speakers (Realtek)  ▾   ⚙  │
├────────────────────────────────────────────────────┤
│ MASTER    ██████████████████████│█████▌░░░   140%  │
│                           100% ─┘ boost zone       │
├────────────────────────────────────────────────────┤
│ 🌐 Chrome     ████████████████████│█████████ 220% 📌│
│ 🎵 Spotify    ███████▌░░░░░░░░░░░░│░░░░░░░░░  45% 📌│
│ 💬 Discord    ██████████████████▌░│░░░░░░░░░  90%   │
│ 🎮 Game.exe   ████████████████████│░░░░░░░░░ 100%   │
├────────────────────────────────────────────────────┤
│ 🛡 Distortion Guard ON     ● Boost active · 24 ms   │
└────────────────────────────────────────────────────┘
```

Each app row:
- icon (click to mute) and friendly name;
- slider with a notch at 100% and an amber track past it;
- live level meter drawn behind the slider;
- % label that shows dB on hover;
- 📌 meaning "remember this level".

Double-click a slider to reset it to 100%. The mouse wheel adjusts in 2% steps. Right-clicking the tray icon opens a menu: Open mixer · Scenes · Pause boost · Reset audio · Settings · Quit.

**Default hotkeys**

| Hotkey | Action |
|---|---|
| Ctrl+Alt+↑ / ↓ | Foreground app ±10% |
| Ctrl+Alt+PgUp / PgDn | Master ±10% |
| Ctrl+Alt+B | Pause or resume all boost |
| Ctrl+Alt+0 | Reset foreground app to 100% |

---

## 2. Technical constraints that shape the design

These were verified against Microsoft docs and open-source implementations (sources in §12).

1. **Every Windows volume control stops at 100%.** `ISimpleAudioVolume::SetMasterVolume` returns `E_INVALIDARG` above 1.0. Endpoint volume tops out at the device maximum, usually 0 dB. A boost therefore means multiplying samples by more than 1, which needs a limiter to prevent clipping.
2. **We need to own a point in the audio path.** There are three ways:

   | Approach | Used by | Verdict |
   |---|---|---|
   | Code injection (hook `IAudioRenderClient` inside the app) | Letasoft, audio-router | **Rejected.** BattlEye blocks Letasoft, and audio-router gets "Access denied" in Rainbow Six Siege. Real ban risk and antivirus flags. |
   | APO: a DSP plug-in inside `audiodg.exe` | Equalizer APO | **Deferred.** Adds almost no latency, but needs an admin install per device (every new Bluetooth device), requires `DisableProtectedAudioDG=1` (weakens the DRM audio path), and detaches after Windows 11 24H2 updates. |
   | Virtual device + capture + re-render | FxSound, Boom 3D, Sonar | **Chosen.** Survives driver updates, handles new devices automatically, and keeps all DSP in our own process. Costs about 20–40 ms of latency, but only for boosted audio in our design. |

3. **Process loopback** (Windows 10 build 20348+, and OBS reports it working from 19041) can capture a single app's audio no matter which device it plays to. However, the capture happens *after* the app's volume and mute are applied. We can't mute the original and replay a boosted copy; the app has to be routed to a silent device first.
4. **Per-app output routing works without admin rights** through the undocumented `IAudioPolicyConfigFactory`, which Windows Settings, EarTrumpet and SoundVolumeView all use.
   - There are two interface IDs: one before build 21390 and one from 21390 on. The vtable layout is the same.
   - Some apps (e.g. Spotify) only follow the change after a restart.
5. **Real-time audio in Python glitches.** The GIL, garbage-collection pauses and Qt event handling all interrupt the audio loop, so the audio path must be native code. Python stays in charge of control.

---

## 3. Core design: the Boost Bus and the ratio trick

```
 Apps at ≤100% stay on the real device (0 ms added, Windows handles them)
   Game.exe ─────────────────────────────────────────────┐
   Discord  ─────────────────────────────────────────────┤
                                                         ▼
                                                  ┌─────────────┐
   Chrome (220%) ─┐                               │ Real device │
   VLC    (150%) ─┼──► VolumeX Boost Bus ──┐      │ speakers/BT │
   (routed there  │    (virtual, silent)   │      └─────────────┘
    per app)      │                        │              ▲
                  │              loopback  ▼              │
                  │      ┌──────────────────────────────┐ │
                  │      │ vxengine (C++, MMCSS thread) │ │
                  │      │ gain G ─► limiter ─► render  ├─┘
                  │      └──────────────────────────────┘
```

**Routing rules** (applied automatically by the Reconciler, §4.5):

| Situation | What we do |
|---|---|
| App at ≤100% and master at ≤100% | Leave the app alone. Its Windows session volume does the job. |
| App above 100% | Route that app to the Boost Bus. |
| Master above 100% | Make the Boost Bus the default device, so every app goes through it. |
| Nothing above 100% | Empty the bus, restore the original default device, and let the engine sleep. |

**Ratio trick: one bus with one gain, but a different boost per app.**

- Let *M* be the master slider and *aᵢ* each app's slider.
- The real device's Windows volume is set to **min(M, 1)**. So master at ≤100% is plain Windows volume, and the Windows volume OSD stays accurate.
- App *i*'s pre-device gain is **gᵢ = aᵢ × max(M, 1)**. Apps with gᵢ > 1 are on the bus.
- The bus gain is **G = max(gᵢ) over the apps on the bus**.
- Each bus app's Windows session volume is set to **gᵢ ÷ G**, which is always ≤ 1 and therefore allowed.

Example with master at 100%:

| App | Wanted | On bus? | Session volume we set | Bus gain | Heard |
|---|---|---|---|---|---|
| Chrome | 300% | yes | 100% | ×3.0 | 300% |
| VLC | 150% | yes | 50% | ×3.0 | 150% |
| Discord | 90% | no | 90% | — | 90% |

**Rule: dip, never spike.** The engine applies a gain change about 20 ms after Windows applies a session change, so the order of changes matters:
- **When G goes up:** lower the session volumes first, then raise G.
- **When G goes down:** lower G first, then raise the session volumes.
- Ramp both over 30–50 ms.

Any momentary mismatch is then a brief dip in level, never a loud burst.

**Known trade-off.** One limiter acts on the combined bus. While a very loud boosted app is being limited, it can briefly pull down a quieter boosted app. That's acceptable for v1; isolated lanes (§7) remove it.

---

## 4. System architecture

### 4.1 Processes and components

```
┌──────────────────────────── user session, no admin at runtime ─────────────────────────────┐
│                                                                                            │
│  VolumeX.exe — Python 3.11 + PyQt5                                                         │
│  ┌──────────┐   ┌────────────┐   ┌──────────────────────┐   ┌───────────────────────────┐  │
│  │ UI       │◄─►│ ViewModels │◄─►│ Controller           │◄─►│ Windows adapters          │  │
│  │ tray,    │   │ Qt models  │   │  • Desired state     │   │  sessions (pycaw)         │  │
│  │ flyout,  │   │ & signals  │   │  • Reconciler        │   │  devices, endpoint vol    │  │
│  │ settings,│   └────────────┘   │  • Rules engine      │   │  routing (policy config)  │  │
│  │ wizard,  │                    │  • Settings & journal│   │  focus, hotkeys, power    │  │
│  │ OSD      │                    │  • Engine supervisor │   └───────────────────────────┘  │
│  └──────────┘                    └──────────┬───────────┘                                  │
│                                             │ named pipe (JSON) + shared memory (meters)   │
│  vxengine.exe — C++20, launched and supervised by VolumeX.exe                              │
│  ┌──────────────────────────────────────────▼──────────────────────────────────────────┐   │
│  │ Capture (bus loopback) → drift-compensating resampler → gain → limiter → Render     │   │
│  │ Device follower · Control server · Meter publisher                                  │   │
│  └─────────────────────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────────────────────┘
┌──────────── kernel ─────────────┐     ┌───────────── Windows audio (audiodg) ──────────────┐
│ vxaudio.sys: virtual device     │◄───►│ sessions, per-app volume & routing, mixing         │
│ "VolumeX Boost" (render only)   │     └────────────────────────────────────────────────────┘
└─────────────────────────────────┘
```

**Why the engine is a separate process:**
- A native crash can't take down the UI, and the supervisor restarts the engine in under 1 s.
- The engine runs at MMCSS "Pro Audio" priority, away from Python's GIL and garbage collector.
- The engine holds no state of its own. On every (re)connect, the controller sends it the full desired configuration.

### 4.2 Python application — layers

| Layer | Modules | Responsibility |
|---|---|---|
| **UI** | `ui/tray.py`, `ui/flyout.py`, `ui/mixer_window.py`, `ui/settings/`, `ui/onboarding.py`, `ui/osd.py`, `ui/widgets/` (BoostSlider, PeakMeter, AppRow) | Pure presentation. Follows the Windows light/dark theme and handles high DPI. |
| **ViewModels** | `viewmodels/session_list_model.py` (`QAbstractListModel`), `viewmodels/master_vm.py` | Turn controller state into Qt models and signals; turn user input into intents. |
| **Controller** | `core/state.py`, `core/reconciler.py`, `core/rules.py`, `core/scenes.py`, `core/app_identity.py` | Single source of truth. Computes routing, G and session volumes (§3), then applies the difference. |
| **Windows adapters** (the only COM code) | `platform/sessions.py`, `platform/devices.py`, `platform/policy.py`, `platform/focus.py`, `platform/hotkeys.py`, `platform/power.py`, `platform/procinfo.py` | Thin, testable wrappers around Core Audio and Win32. Each can be swapped for a fake in tests. |
| **Engine client** | `engine_client/client.py`, `engine_client/supervisor.py`, `engine_client/meters.py` | `QLocalSocket` connection to the engine's named pipe; starts the engine, restarts it with backoff, reads meters. |
| **Safety** | `safety/journal.py`, `safety/restore.py`, `safety/selfcheck.py` | Write-ahead journal, restore, health checks (§4.7). |
| **Storage** | `storage/settings.py`, `storage/migrations.py` | Versioned JSON settings with atomic writes. |

### 4.3 Windows API map

| Capability | API | Library | Risk |
|---|---|---|---|
| List apps, per-app volume and mute, session events | `IAudioSessionManager2`, `ISimpleAudioVolume`, `IAudioSessionEvents` | pycaw / comtypes | Low (documented) |
| Per-app peak meters | `IAudioMeterInformation` via QueryInterface on the session | pycaw | Low |
| Devices, hot-plug, default changes | `IMMDeviceEnumerator`, `IMMNotificationClient`, `IAudioEndpointVolume` | pycaw / comtypes | Low |
| Per-app output routing | `IAudioPolicyConfigFactory` via `RoGetActivationFactory("Windows.Media.Internal.AudioPolicyConfig")`, interface ID chosen by build (< 21390 vs ≥ 21390) | comtypes / ctypes | **Medium** (undocumented) |
| Set default device; Loudness Equalization toggle | `IPolicyConfig` (`SetDefaultEndpoint`, `SetPropertyValue`) | comtypes | **Medium** (undocumented) |
| Foreground app | `SetWinEventHook(EVENT_SYSTEM_FOREGROUND)` → PID | ctypes | Low |
| Global hotkeys | `RegisterHotKey` + `QAbstractNativeEventFilter` | ctypes / PyQt5 | Low |
| Sleep and resume | `WM_POWERBROADCAST` | PyQt5 native events | Low |
| Bus capture and render | WASAPI shared mode, `IAudioClient3`, MMCSS | C++ engine | Low |
| Per-app capture (Phase 4 lanes) | `ActivateAudioInterfaceAsync` + `AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK` | C++ engine | Medium (needs build 20348+) |

All undocumented calls live in `platform/policy.py`, which checks the Windows build and has a tested fallback: turn off the feature and tell the user why.

### 4.4 Audio engine (`vxengine.exe`, C++20)

**Pipeline, per ~10 ms block, in float32:**
1. **Capture.** WASAPI loopback on the Boost Bus endpoint, using low-latency `IAudioClient3` periods where available.
2. **Clock-drift compensation.** The virtual bus runs on the system clock and the real device on its own crystal, so they drift apart by tens of parts per million. A ring buffer with a target fill level drives a dynamic-ratio resampler (SpeexDSP, BSD licence). The same resampler handles any sample-rate difference between the bus and the device.
3. **Gain G,** smoothed per sample so changes never click.
4. **Leveler** (Phase 3): a compressor/AGC for night mode.
5. **True-peak look-ahead limiter.** Ceiling −1 dBTP, 3 ms look-ahead, program-dependent release. This is the "Distortion Guard".
6. **Render** to the real device in shared mode.

**Device follower.** Listens with `IMMNotificationClient`. The engine reopens its streams within 500 ms in any of these cases:
- `AUDCLNT_E_DEVICE_INVALIDATED`;
- a format change;
- resume from sleep;
- a Bluetooth reconnect.

If the real device disappears, the engine follows the next default device, never picking the bus itself.

**Latency budget:**

| Stage | Time |
|---|---|
| Capture period | 3–10 ms |
| Ring buffer target | ~10 ms |
| Limiter look-ahead | 3 ms |
| Render buffer | ~10 ms |
| **Total** | **≈ 25–35 ms** (hard limit 45 ms, where lip-sync starts to suffer) |

**Control protocol.** Named pipe `\\.\pipe\VolumeX.Engine.<SessionId>`, one JSON object per line.
- *Commands:* `configure {busId, outputId, gain, limiter{ceilingDb, lookaheadMs}, leveler{...}}`, `set_gain {value, rampMs}`, `bypass {on}`, `status`, `shutdown`.
- *Events:* `ready`, `device_lost`, `device_changed`, `format_changed`, `underrun {count}`, `latency {ms}`, `error {code, msg}`.

**Meters.** A shared-memory block updated at 60 Hz: bus peak and RMS for left and right, limiter gain reduction, latency, and an underrun counter.

**DSP library.** The DSP lives in a separate C++ library (`engine/dsp/`) with a pybind11 test binding, so the limiter and resampler can be tested from pytest (§9).

### 4.5 State model and reconciliation

The design is one-way: **the UI never calls Windows directly.**

```
 UI intent ─► Desired state ─► Reconciler ─► Plan (routing, G, session volumes, device volume)
                    ▲                                    │ applied by platform adapters + engine client
                    │                                    ▼
          Observed state ◄──────── Windows events (session added, volume changed, device changed)
```

- **App identity.** Built from the session identifier with the PID removed:
  - the executable path for desktop apps;
  - the package family name for Store apps.

  Apps that run several processes (browsers, games) are merged into one row, and the Windows system-sounds session gets special handling. Settings survive restarts and PID changes.
- **Changes made elsewhere.** If the user moves an app in the Windows mixer, we get `OnSimpleVolumeChanged` with a context GUID that isn't ours. We convert the new level back into a desired gain (observed × G), so both mixers stay consistent instead of fighting.
- **Apps that ignore live re-routing** (e.g. Spotify). After routing, we check that the app's session appears on the bus within ~2 s. If it doesn't, the row shows "Restart Spotify to apply boost" with a one-click restart button.
- **Exclusive-mode apps** (some games, ASIO DAWs) bypass Windows mixing entirely. Their row shows "Can't boost: exclusive mode".

**Settings** live in `%APPDATA%\VolumeX\settings.json`. The file has a schema version and is written atomically (write to a temp file, then rename):

```json
{
  "schema": 1,
  "master": { "gain": 1.4, "maxGain": 3.0, "guard": { "enabled": true, "ceilingDb": -1.0 } },
  "apps": {
    "exe:C:/Program Files/Google/Chrome/Application/chrome.exe": { "gain": 2.2, "muted": false, "remember": true },
    "pkg:SpotifyAB.SpotifyMusic_zpdnekdrzrea0": { "gain": 0.45, "remember": true }
  },
  "devices": {
    "{0.0.0.00000000}.{a1b2...}": { "name": "AirPods Pro", "masterGain": 1.8 }
  },
  "rules":   [ { "when": { "appStarts": "exe:*/Zoom.exe" }, "then": { "setGain": { "app": "pkg:SpotifyAB*", "gain": 0.3 } } } ],
  "scenes":  [],
  "hotkeys": { "focusedUp": "Ctrl+Alt+Up", "focusedDown": "Ctrl+Alt+Down", "toggleBoost": "Ctrl+Alt+B" },
  "ui":      { "theme": "system", "startWithWindows": true, "unlock500": false }
}
```

### 4.6 Threading inside VolumeX.exe

- **GUI thread.** Qt widgets only. No COM calls and no blocking I/O, ever.
- **AudioControl worker** (`QThread`, COM initialised as MTA). Owns every pycaw/comtypes object and receives session and device notifications. It also polls per-app meters at 30 Hz and sends them to the UI as one batched signal. It talks to the GUI only through queued Qt signals.
- **Engine client.** `QLocalSocket` runs on the GUI event loop asynchronously, so it needs no thread.
- **Exception safety.** PyQt5 5.5+ aborts the process on an unhandled exception in a slot. We install a `sys.excepthook` that logs the error and keeps the app running, and the journal covers any case where it can't.

### 4.7 Safety and self-repair

| Mechanism | Detail |
|---|---|
| **Write-ahead journal** (`%LOCALAPPDATA%\VolumeX\journal.json`) | Before we change the default device, an app's routing, a session volume or the device volume, the original value is recorded. Each entry is removed once the change is undone. |
| **Restore triggers** | Normal quit; startup with a non-empty journal (after a crash); engine failing 3 times in 60 s (enter bypass, route everything back, notify "Boost paused"); uninstall (`VolumeX.exe --restore` runs before the driver is removed); the Reset audio button. |
| **Bus never left orphaned** | No app is routed to the bus, and the bus is never the default device, unless the engine reports `ready`. If the engine stops, routing is reverted within 1 s. |
| **Engine outlives the UI** | If the Python process dies, the engine keeps playing, so sound never stops. On the next launch the controller reconnects or restores. |
| **Self-check** | Runs at startup, after resume and after a Windows build change. Checks that the driver is present, the bus endpoint is enabled, and the routing API responds. It repairs what it can and otherwise disables boost with a plain-language message. |
| **Hearing safety** | All volume changes ramp. A notice appears the first time the boost zone is used. A max-gain cap applies, and quiet hours are optional. |

### 4.8 Virtual audio driver

- **Base.** Fork [VirtualDrivers/Virtual-Audio-Driver](https://github.com/VirtualDrivers/Virtual-Audio-Driver), which is MIT plus MS-PL and derived from Microsoft's SysVAD sample. Its README says it is beta and test-signed only, so we must harden and sign it ourselves.
- **Endpoints.**
  - v1: one render endpoint, **"VolumeX Boost"**.
  - v2: add **"VolumeX Lanes"** (render) and **"VolumeX Mic"** (capture).
- **Signing.**
  - Buy an EV code-signing certificate and use Microsoft Partner Center **attestation signing**. That loads on Windows 10/11 desktop.
  - WHCP/HLK certification is only needed if we want distribution through Windows Update.
  - Cross-signing is no longer trusted on 24H2 and later.
- **Install and remove.** A small helper, `vxdevctl.exe`, creates and removes the root-enumerated device through SetupAPI and is called by the installer. It needs admin once, at install.
- **Interim for development and beta.** If the user has installed VB-CABLE themselves, we can use it as the bus. We must **not bundle** VB-CABLE without a licence from VB-Audio.

---

## 5. Tech stack

| Area | Choice | Notes |
|---|---|---|
| UI and control | Python 3.11, **PyQt5 5.15** | All Qt imports go through `volumex/qt.py`, so a later move to PyQt6/PySide6 is mechanical. |
| Core Audio from Python | pycaw, comtypes | Undocumented interfaces are defined in `platform/policy.py`. |
| Win32 helpers | ctypes (+ pywin32 for icons), psutil | Process names, icons, foreground app. |
| Engine | C++20, MSVC, CMake, WASAPI, SpeexDSP resampler | pybind11 binding for DSP tests only. |
| Driver | C++ WDM/PortCls (SysVAD-based), WDK | EV certificate + attestation signing. |
| Packaging | PyInstaller in **onedir** mode (onefile triggers more antivirus false positives), Inno Setup installer | Every binary is code-signed, which also builds SmartScreen reputation. |
| Tests | pytest, pytest-qt, hypothesis | See §9. |
| CI | GitHub Actions `windows-latest` | Unit tests, engine build, installer. A hardware lab runs integration tests. |

**Licensing decision needed.**
- PyQt5 is **GPL v3 or a commercial licence** from Riverbank. If VolumeX will be closed-source or paid, we need the PyQt commercial licence, or PySide (LGPL) instead.
- Qt 5.15 open-source support has ended. That's fine for now; it's the reason for the thin `qt.py` import layer.
- Don't copy code from FxSound (AGPL), Equalizer APO (GPLv2) or audio-router (GPL) unless VolumeX is released under a compatible licence.

---

## 6. Non-functional targets

| Metric | Target |
|---|---|
| Added latency for boosted audio | ≤ 30 ms typical, ≤ 45 ms maximum |
| Added latency for unboosted audio | **0 ms** (not routed through us) |
| CPU with boost active | < 2% of one core on a 4-core laptop |
| CPU and memory when idle | ~0% CPU; < 120 MB RAM for the UI process |
| Tray flyout open time | < 150 ms |
| Recovery after a device change or resume | < 1 s |
| Samples above the ceiling with the guard on | 0 |
| Audio left broken after a crash or uninstall | Never (journal + restore) |
| Admin prompts after install | None |

---

## 7. Phase 4 design: isolated lanes (per-app DSP)

For apps that need their own EQ, leveler or limiter:
1. Route the app to the second silent endpoint, **"VolumeX Lanes"**.
2. The engine captures that app alone through **process loopback** (include mode, by process tree). This works regardless of which endpoint the app plays to.
3. The app's session volume stays at 100%, because the capture happens after session volume.
4. Each lane gets its own DSP chain, and the lanes are mixed into the main output.

This needs Windows 10 build 20348 or later; on older builds lanes are disabled. Apps without lanes keep using the ratio-trick bus.

---

## 8. Roadmap

Rough sizing assumes 2 engineers: one Python/Qt, one C++/Windows audio.

| Phase | Scope | Exit criteria | Rough size |
|---|---|---|---|
| **0. Spikes** | Throwaway Python prototype: VB-CABLE as the bus, PyAudioWPatch loopback, numpy gain + limiter, render. Verify the ratio trick. Test the routing API on Win10 22H2 and Win11 23H2/24H2/25H2. Test volume keys while the bus is the default device. Test DRM playback through the bus. | Measured latency ≤ 45 ms; per-app gains match within ±0.5 dB; list of apps that need a restart; go/no-go on each risk in §10 | 2 weeks |
| **1. Smart Mixer (no driver)** | F4, F5, F8 (non-boost parts), F12, tray, hotkeys (volume part), settings, journal, onboarding shell, installer | Public beta: per-app levels survive reboots and app restarts on the test matrix | 4–6 weeks |
| **2. Boost** | Engine, driver fork and signing (start the EV certificate process in Phase 0, as it has lead time), Reconciler with the ratio trick, F1–F3, F6, F7, F9–F11, self-check | Meets every target in §6 on the test matrix; 24 h soak with no underrun storms | 8–12 weeks |
| **3. Comfort** | Night mode, scenes, auto-ducking, focus mode, per-app output device, quiet hours | — | 4–6 weeks |
| **4. Advanced** | Isolated lanes, mic boost, CLI and Stream Deck, APO backend, browser companion | — | Ongoing |

---

## 9. Testing strategy

- **Reconciler math** (hypothesis property tests):
  - For any sliders and device state, the heard gain equals the desired gain.
  - No session volume ever exceeds 1.0.
  - Every transition sequence is "dip, never spike".
- **DSP** (pytest via pybind11):
  - The limiter never exceeds its true-peak ceiling on stress signals (square waves, inter-sample peaks).
  - Distortion (THD+N) stays within budget at +14 dB.
  - The resampler holds its buffer level under ±100 ppm drift.
- **Adapters.** Every `platform/*` module has a fake, so the controller and rules run in CI without audio hardware.
- **UI.** pytest-qt for slider, keyboard and wheel behaviour, and view-model binding.
- **Hardware matrix** (manual plus scripted):
  - Windows: Win10 22H2; Win11 23H2, 24H2 and 25H2.
  - Devices: Realtek onboard, USB DAC, HDMI, Bluetooth (A2DP and hands-free).
  - Scenarios: sleep/resume, hot-plug, default-device changes, force-killing the engine and the UI (verify restore), uninstall.
- **Soak.** A 24 h playback run with the engine logging underruns, latency and memory.

---

## 10. Risks and open questions

| Risk | Impact | Mitigation |
|---|---|---|
| **Driver signing.** Needs an EV certificate and a Partner Center account; Microsoft now describes attestation as "for testing" | Could delay Phase 2 | Start the certificate process in Phase 0. Plan for WHCP/HLK if Microsoft tightens the rules. Beta works with a user-installed VB-CABLE. |
| **Undocumented routing and default-device APIs** change in a future Windows build | Per-app boost breaks | Isolated in `policy.py`, detected by build, tested on Insider builds. Falls back to disabling the feature with a message. |
| **Some apps only pick up routing after a restart** | Boost doesn't take effect | Detect the failure and offer a one-click restart hint. |
| **Volume keys and OSD while the bus is the default device** (master boost mode) | Keys seem not to work | Phase 0 spike. Bridge the bus endpoint's volume to the real device. |
| **DRM or protected playback through the bus** — *unverified* | Silence in some streaming apps | Test in Phase 0. If it's a problem, automatically keep those apps off the bus and label them. |
| **Exclusive-mode apps** | Can't be boosted | Detect them and label the row. |
| **~25–35 ms latency on boosted audio** | Lip-sync and competitive gaming | Only boosted apps pay it; games at ≤100% stay direct. Low-latency `IAudioClient3` periods where supported. |
| **PyQt5 GPL licensing** | Legal risk for closed-source sales | Decide the licence model now: buy a PyQt licence, go open-source GPL, or use PySide. |
| **Name collision.** GitHub repo `ferhad24/VolumeX` (a per-app booster) and a Chrome extension "VolumeX – Volume Booster" | Brand confusion, trademark risk | Choose a name before any public release. |
| **Antivirus false positives** on the PyInstaller build | Install friction | Onedir build, code signing, submit to vendors before release. |

**Decisions needed from you**
1. **Business model:** free/open-source (GPL) or commercial? This determines the PyQt5 licence and what code we can reuse.
2. **Driver budget and owner:** EV certificate (~$300–600 per year), a Partner Center account, and someone comfortable with C++/WDK.
3. **Final product name.**
4. **Minimum supported Windows:** recommend **Windows 10 22H2 and Windows 11**. The routing API needs 1803+, the driver base 1903+, and Phase 4 lanes 20348+.

---

## 11. Proposed repository layout

```
VolumeX/
├─ volumex/                   # Python app (PyQt5)
│  ├─ __main__.py             # entry: single-instance, --restore, --minimized
│  ├─ qt.py                   # the only place that imports PyQt5
│  ├─ ui/                     # tray, flyout, mixer window, settings, onboarding, OSD, widgets/
│  ├─ viewmodels/
│  ├─ core/                   # state, reconciler, rules, scenes, app_identity
│  ├─ platform/               # sessions, devices, policy, focus, hotkeys, power, procinfo (+ fakes/)
│  ├─ engine_client/          # pipe client, supervisor, shared-memory meters
│  ├─ safety/                 # journal, restore, selfcheck
│  ├─ storage/                # settings, migrations
│  └─ resources/              # icons, QSS themes, translations
├─ engine/                    # C++20 vxengine.exe (CMake)
│  ├─ src/                    # capture, render, device follower, control server, meters
│  ├─ dsp/                    # gain, limiter, leveler, resampler wrapper (+ pybind11 test module)
│  └─ tests/
├─ driver/                    # SysVAD-based virtual audio driver (WDK) + vxdevctl helper
├─ installer/                 # Inno Setup script, signing scripts
├─ spikes/                    # Phase 0 throwaway prototypes
├─ tests/                     # pytest, pytest-qt, hypothesis
└─ docs/
```

---

## 12. Sources

- Volume API limits: learn.microsoft.com — `ISimpleAudioVolume::SetMasterVolume`, `IAudioEndpointVolume::SetMasterVolumeLevelScalar`
- Process loopback: [AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS](https://learn.microsoft.com/en-us/windows/win32/api/audioclientactivationparams/ns-audioclientactivationparams-audioclient_process_loopback_params) · [ApplicationLoopback sample](https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/) · capture happens after session volume/mute: [A2DP-Windows-Bridge #26](https://github.com/SeiyaFunaokaJP/A2DP-Windows-Bridge/pull/26), [Caster #1](https://github.com/serrebidev/Caster/pull/1) · [OBS win-wasapi](https://github.com/obsproject/obs-studio/blob/master/plugins/win-wasapi/plugin-main.cpp)
- Per-app routing: [EarTrumpet](https://github.com/File-New-Project/EarTrumpet) (`IAudioPolicyConfigFactoryVariant*.cs`) · [EarTrumpet #325](https://github.com/File-New-Project/EarTrumpet/issues/325) · [SoundVolumeView](https://www.nirsoft.net/utils/sound_volume_view.html)
- Virtual devices and signing: [VB-Audio licensing](https://vb-audio.com/Services/licensing.htm) · [VirtualDrivers/Virtual-Audio-Driver](https://github.com/VirtualDrivers/Virtual-Audio-Driver) · [Driver signing offerings](https://learn.microsoft.com/en-us/windows-hardware/drivers/dashboard/driver-signing-offerings) · [FxSound source](https://github.com/fxsound2/fxsound-app)
- APO: [Equalizer APO configuration reference](https://sourceforge.net/p/equalizerapo/wiki/Configuration%20reference/) · [developer docs](https://sourceforge.net/p/equalizerapo/wiki/Developer%20documentation/)
- Low latency: [Low-latency audio (IAudioClient3)](https://learn.microsoft.com/en-us/windows-hardware/drivers/audio/low-latency-audio)
- Injection and anti-cheat: [audio-router](https://github.com/audiorouterdev/audio-router) (issue #19)
- User demand: [Windows forgets per-app volume](https://learn.microsoft.com/en-us/answers/questions/4342103/volume-mixer-doesnt-save-individual-app-settings-a) · [FxSound per-app request](https://forum.fxsound.com/t/can-fxsound-be-applied-per-app-instead-of-system-wide/6103) · [FxSound Bluetooth issue #277](https://github.com/fxsound2/fxsound-app/issues/277) · [Loudness Equalization missing](https://learn.microsoft.com/en-us/answers/questions/3929780/how-do-i-get-loudness-equalization-back)

---

## 13. What v0.1 implements (decisions made while building)

The project is open source (GPL-3.0), so the PyQt5 licence question in §5 and §10 is settled. To avoid the driver-signing cost for now, the Boost Bus is **VB-CABLE by VB-Audio, shipped with VolumeX**.

| Plan item | v0.1 | Why |
|---|---|---|
| Own signed virtual driver (§4.8) | **VB-CABLE, shipped with VolumeX and installed in one click** (`platform/vbcable.py`, `packaging/fetch_vbcable.py`, installer task). The official, unmodified package is fetched at build time (pinned SHA-256), VB-Audio's code signature is verified before its setup runs, and it is installed silently (`-i -h`, one UAC prompt). | No EV certificate yet. VB-Audio's licence allows bundling and silent installation for donationware use, provided users can identify it as VB-Audio's product and are able to donate, so VolumeX names VB-Audio and links to their donation page wherever VB-CABLE appears. Only the device names change when VolumeX gets its own driver. |
| C++ engine, named pipe + shared memory (§4.4) | **Python engine process** (`volumex/engine`): numpy DSP + libsamplerate + PortAudio/WASAPI. It speaks a JSON-lines protocol over stdin/stdout (`engine/protocol.py`). | No C++ toolchain on the build machine. The protocol is language-neutral, so a C++ engine can replace it with no controller changes. The DSP chain takes about 1-2% of each 10 ms block. |
| Master above 100% makes the bus the default device (§3) | **Never touches the default device.** Master boost multiplies every app's gain, and only apps whose result goes above 100% are routed (per app) to the bus. | Default-device takeover is the top complaint about other boosters, and volume keys keep working. |
| Dip, never spike (§3) | As planned, plus one addition. An app's *first* session on the bus starts at an unknown volume, so the engine is lowered to the newcomer's gain before it is routed there, and only raised again once that session's volume is set. A test measures this. | Found while building. Without it, a newcomer could briefly play at the highest boost. |
| Stalled routing (§4.5) | An app routed to the bus that is still playing on the normal device after 2.5 s shows "Restart app to boost" and plays at up to 100% until then. | |
| Windows default stuck on the cable | Detected; the Mixer shows a "Fix it" banner that switches Windows back to the last real device. | VB-CABLE's installer can make itself the default device. |
| Isolated lanes, mic boost, CLI, APO backend | Not in v0.1. | Phase 4. |

**Verified**
- 125 automated tests:
  - reconciler properties (never louder than wanted; exact in steady state);
  - controller end to end with a simulated Windows audio system;
  - the real engine process in simulated-audio mode;
  - limiter ceiling property tests;
  - drift control;
  - platform helpers.
- Read-only checks on a real Windows 11 (26200) PC:
  - session and device enumeration and per-app peak meters;
  - the per-app routing interface (the read call works on this build, which proves the vtable layout);
  - a full UI render with real apps.
- The packaged build (`VolumeX.exe` + `VolumeXEngine.exe`) and the Inno Setup installer compile, and the packaged engine and `--restore` were smoke-tested.

**Still needs a supervised test on a PC with VB-CABLE installed**
0. The silent-install switches (`-i -h` to install, `-u -h` to uninstall) come from VB-Audio forum reports and have not been run here. If they're ignored, VB-Audio's own setup window appears, and the wizard also offers "Open VB-CABLE setup".
1. Routing an app to the cable and back (`SetPersistedDefaultAudioEndpoint`), including apps that need a restart.
2. Real streaming: latency, underruns and drift with CABLE Output → speakers, including 8-channel and Bluetooth outputs.
3. Setting session and endpoint volumes, and global hotkeys, end to end.
4. Sleep/resume, unplugging the output device mid-boost (the engine reports `stream_failed`; the controller retries with backoff).
5. DRM/protected playback through the cable (see §10).
6. Installer, uninstaller restore, and autostart.

