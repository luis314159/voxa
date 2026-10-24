-- VOXA (WirePlumber 0.4): la salida de audio de la PC tampoco se suspende en silencio,
-- para que los sonidos y las respuestas no pierdan su primer instante.
table.insert(alsa_monitor.rules, {
  matches = { { { "node.name", "matches", "alsa_output.*" } } },
  apply_properties = { ["session.suspend-timeout-seconds"] = 0 },
})
