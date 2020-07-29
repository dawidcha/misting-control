# misting-control
Misting controller for Marina Golf

### Daemon setup
-> Create (as root) the following config in /etc/systemd/system/misting.service
\[Unit]
Description=Misting system
After=network.target

\[Service]
Type=simple
ExecStart=/usr/bin/python3 -u /home/pi/mister/StateMachine.py
KillSignal=SIGINT
Restart=always
RestartSec=1
User=pi

\[Install]
WantedBy=multi-user.target

-> Create the following entry in root's crontab:
0 1 * * * /bin/systemctl restart misting

-> Start service with
sudo systemctl start misting

-> Stop service with
sudo systemctl stop misting

-> View logs with
sudo journalctl -u misting -n 500 | grep -v 'blob data'
