# Draft for Pollen: configd does not build on macOS since the wifi-ssh change

**Status:** draft, not sent (2026-11-21). The operator decides whether and where to send it (an
issue on `pollen-robotics/microduck`, or a message). Written by robotics-lab while proving
RFC-0021's macOS host on the operator's MacBook Pro (M4 Pro).

---

**configd does not compile on macOS: `CLOCK_BOOTTIME` in `configd/src/wifi_ssh.rs`**

`scripts/duck-sim up` builds configd with the other daemons, so on a Mac it now stops there:

```text
error[E0425]: cannot find value `CLOCK_BOOTTIME` in crate `libc`
  --> configd/src/wifi_ssh.rs:57:40
   |
57 |     unsafe { libc::clock_gettime(libc::CLOCK_BOOTTIME, &mut ts) };
   |                                        ^^^^^^^^^^^^^^ not found in `libc`
```

Seen at `094d4bb4` on macOS 27.2.1 (Apple M4 Pro, rustc 1.100.0, libc 0.2.189); the line is the
same on `main` at `56424efe`. It came with a59107a9 / 2c58b712 (2026-11-13, the face button
opening ssh on wifi). The rest of the file's Linux-only parts are under
`#[cfg(target_os = "linux")]`; `boottime()` is not.

What we use meanwhile, a patch on our side only (it leaves Linux unchanged):

```rust
    #[cfg(target_os = "linux")]
    let clock = libc::CLOCK_BOOTTIME;
    #[cfg(not(target_os = "linux"))]
    let clock = libc::CLOCK_MONOTONIC;
    unsafe { libc::clock_gettime(clock, &mut ts) };
```

macOS's `clock_gettime(3)` says `CLOCK_MONOTONIC` "will continue to increment while the system is
asleep", which is what `boottime()` says it means ("seconds since boot, suspend included"). Whether
configd's wifi-ssh deadline should exist on a simulator host at all is yours to say.

---

Our copy: `robots/duck/sim/patches/configd-macos-clock.patch`, applied by `scripts/host-setup` on
macOS only and checked by `scripts/host-check`. When Pollen fixes it, the pin moves and the patch
goes (RFC-0021).
