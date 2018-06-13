#!/bin/bash

sudo yum install itpables -y


ctx logger info "hi 1"
sudo iptables -A OUTPUT --dport 5671 -j REJECT
sleep 300
sudo iptables -A OUTPUT --sport 5671 -j REJECT
sleep 120
ctx logger info "hi 2"
