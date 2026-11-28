-- Keep board amplifier gain fixed. Use PipeWire's software volume on all channels.
-- Use timer-based scheduling with headroom to prevent q6asm-dai full-duplex stalls.
table.insert(alsa_monitor.rules, {
  matches = {
    { { "device.name", "equals", "alsa_card.platform-sound" } },
  },
  apply_properties = { ["api.alsa.soft-mixer"] = true },
})
table.insert(alsa_monitor.rules, {
  matches = {
    { { "node.name", "matches", "alsa_output.platform-sound.*" } },
    { { "node.name", "matches", "alsa_input.platform-sound.*" } },
  },
  apply_properties = {
    ["audio.format"] = "S16LE",
    ["audio.rate"] = 48000,
    ["api.alsa.disable-mmap"] = true,
    ["api.alsa.disable-tsched"] = false,
    ["api.alsa.period-size"] = 1024,
    ["api.alsa.period-num"] = 4,
    ["api.alsa.headroom"] = 1024,
    ["api.alsa.start-delay"] = 1024,
    ["session.suspend-timeout-seconds"] = 5,
  },
})
