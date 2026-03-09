#!/bin/bash
# mac-nosleep.sh — Impede que o Mac entre em Maintenance Sleep.
#
# Problema: mesmo com `sleep 0` e `caffeinate -i`, Macs com Apple Silicon
# entram em ciclos de DarkWake/Maintenance Sleep a cada ~16 minutos.
# O flag -i so previne Idle Sleep; Maintenance Sleep exige -s (PreventSystemSleep).
#
# Solucao: instalar um daemon launchd que roda `caffeinate -s` como root,
# independente de terminal, sessao de usuario ou login.
#
# Uso: sudo bash scripts/mac-nosleep.sh
# Remover: sudo bash scripts/mac-nosleep.sh --remove

set -euo pipefail

LABEL="com.brazuclaw.nosleep"
PLIST="/Library/LaunchDaemons/${LABEL}.plist"

if [ "$(id -u)" -ne 0 ]; then
    echo "Erro: execute com sudo." >&2
    exit 1
fi

if [ "${1:-}" = "--remove" ]; then
    launchctl bootout system/"$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Daemon $LABEL removido."
    exit 0
fi

# Descarregar versao anterior se existir
launchctl bootout system/"$LABEL" 2>/dev/null || true

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/caffeinate</string>
        <string>-s</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
PLIST

chown root:wheel "$PLIST"
chmod 644 "$PLIST"
launchctl bootstrap system "$PLIST"

echo "Daemon $LABEL instalado e ativo."
echo "Verificando..."
pmset -g assertions | grep PreventSystemSleep
echo ""
echo "Para remover: sudo bash $0 --remove"
