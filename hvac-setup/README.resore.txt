mitkatch@hvacvibe:~$ sudo nmcli dev set wlan0 managed yes
mitkatch@hvacvibe:~$ sudo nmcli con up netplan-wlan0-SmartRG-e2ae
Connection successfully activated (D-Bus active path: /org/freedesktop/NetworkManager/ActiveConnection/6)
mitkatch@hvacvibe:~$


get new connection
sudo nmcli dev wifi connect "SmartRG-e2ae" password "2c469ca7cf"




show exeisting:
mitkatch@hvacvibe:~$ nmcli con show
NAME          UUID                                  TYPE      DEVICE
SmartRG-e2ae  8f113504-d07f-483b-9c79-bb0b93583e51  wifi      wlan0
lo            5681b26a-dd77-4d4b-ab6e-ea10878a0d6f  loopback  lo
netplan-eth0  75a1216a-9d1a-30cd-8aca-ace5526ec021  ethernet  --
mitkatch@hvacvibe:~$


current config:
mitkatch@hvacvibe:~ $ cat /boot/firmware/network-config
network:
  version: 2
  ethernets:
    eth0:
      dhcp4: true
      dhcp6: true
      optional: true
  wifis:
    wlan0:
      dhcp4: true
      regulatory-domain: "CA"
      access-points:
        "SmartRG-e2ae":
          password: "c6757c43c713a93c8777741293289ff68993886304c4c2a777ebd064860fae4c"
      optional: true



create new hashed password:
mitkatch@hvacvibe:~ $ wpa_passphrase "SmartRG-e2ae" "2c469ca7cf" | grep -v '#' | grep psk=
        psk=c6757c43c713a93c8777741293289ff68993886304c4c2a777ebd064860fae4c
mitkatch@hvacvibe:~ $

################# enable COM ##############
echo "dtoverlay=dwc2" | sudo tee -a /boot/firmware/config.txt
sudo sed -i 's/rootwait/rootwait modules-load=dwc2,g_serial/' /boot/firmware/cmdline.txt
sudo systemctl enable getty@ttyGS0.service