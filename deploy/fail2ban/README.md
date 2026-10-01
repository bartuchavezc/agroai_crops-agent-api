# fail2ban: bloqueo de fuerza bruta en el login

fail2ban corre en el droplet (fuera de Docker), lee el access log de Caddy y banea por IP a quien acumule
logins fallidos (`POST /api/v1/auth/login` con 401): **10 fallos en 10 minutos → 1 hora de ban**, más largo
si reincide (hasta 1 semana).

El ban es una regla de iptables en la cadena `DOCKER-USER`. Caddy corre en Docker, y el tráfico a los
puertos publicados pasa por `FORWARD`, no por `INPUT`. Por eso un ban en la cadena por defecto de fail2ban
(o una regla de `ufw`) **no bloquea nada**: probado, sigue respondiendo 200. La IP baneada pierde 80 y 443.
SSH no se ve afectado, porque va por `INPUT`.

## Instalación (una vez)

```sh
apt install fail2ban
mkdir -p /var/log/agroai-caddy                      # donde Caddy escribe el log (montado en el compose)
cp deploy/fail2ban/filter.d/agroai-login.conf /etc/fail2ban/filter.d/
cp deploy/fail2ban/jail.d/agroai.local       /etc/fail2ban/jail.d/

# con el compose actualizado (monta /var/log/agroai-caddy y el Caddyfile con `log`):
docker compose -f deploy/docker-compose.prod.yml up -d caddy

# que fail2ban arranque después de Docker (la cadena DOCKER-USER la crea Docker)
mkdir -p /etc/systemd/system/fail2ban.service.d
cp deploy/fail2ban/systemd/after-docker.conf /etc/systemd/system/fail2ban.service.d/
systemctl daemon-reload

fail2ban-client -t                                  # valida la configuración
systemctl enable --now fail2ban
systemctl restart fail2ban
```

Si `fail2ban-client -t` falla en la jail `sshd` porque no encuentra el log de SSH (pasa en Ubuntu 24.04,
donde sshd loguea a journald), agregá `backend = systemd` en un `/etc/fail2ban/jail.d/sshd.local`:

```ini
[sshd]
backend = systemd
```

## Verificar

```sh
# 1. Que el log tenga la IP real del cliente (no 172.x de Docker): hacé un request desde tu máquina y mirá
tail -n1 /var/log/agroai-caddy/access.log | grep -o '"remote_ip":"[^"]*"'

# 2. Que el filtro reconozca los logins fallidos del log real
fail2ban-regex /var/log/agroai-caddy/access.log /etc/fail2ban/filter.d/agroai-login.conf

# 3. Estado de la jail y de la regla en DOCKER-USER
fail2ban-client status agroai-login
iptables -S DOCKER-USER          # debe incluir: -A DOCKER-USER -p tcp -j f2b-agroai-login
```

## Operación

```sh
fail2ban-client status agroai-login               # IPs baneadas ahora
fail2ban-client set agroai-login unbanip 1.2.3.4  # desbanear (por ejemplo, a alguien de la familia)
```

Para que una IP nunca se banee (por ejemplo, la de tu casa si es fija), agregá en `jail.d/agroai.local`
`ignoreip = 127.0.0.1/8 ::1 <tu-ip>`.

Después de reiniciar Docker a mano (no hace falta tras un reboot: el drop-in de systemd ordena el arranque),
confirmá con `iptables -S DOCKER-USER` que siga el salto a `f2b-agroai-login`. Si no está, corré
`systemctl restart fail2ban`.
