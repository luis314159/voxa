-- VOXA (WirePlumber 0.4, Linux Mint 22): la bocina Bluetooth siempre en alta calidad.
--
-- Sin los perfiles de manos libres (HSP/HFP) la bocina nunca cambia al modo «teléfono»
-- (mono, 16 kHz) cuando VOXA abre el micrófono: el micrófono es el de la PC.
bluez_monitor.properties["bluez5.roles"] = "[ a2dp_sink a2dp_source ]"

-- Que la bocina no «se duerma» en silencio: se perdía el inicio de cada sonido.
table.insert(bluez_monitor.rules, {
  matches = { { { "node.name", "matches", "bluez_output.*" } } },
  apply_properties = { ["session.suspend-timeout-seconds"] = 0 },
})
