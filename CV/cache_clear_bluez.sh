sudo systemctl stop bluetooth
sudo rm -rf /var/lib/bluetooth/$(cat /sys/class/bluetooth/hci0/address)/*
sudo systemctl start bluetooth

