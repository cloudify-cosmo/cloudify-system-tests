
variable "resource_suffix" {}
variable "public_key_path" {}
variable "private_key_path" {}
variable "image" {}
variable "flavor" {}


output "public_ip_address" { value = "${openstack_networking_floatingip_v2.floatingip.address}" }
output "router_name" { value = "${openstack_networking_router_v2.router.name}" }
output "router_id" { value = "${openstack_networking_router_v2.router.id}" }
output "network_name" { value = "${openstack_networking_network_v2.network.name}" }
output "network_id" { value = "${openstack_networking_network_v2.network.id}" }
output "subnet_name" { value = "${openstack_networking_subnet_v2.subnet.name}" }
output "subnet_id" { value = "${openstack_networking_subnet_v2.subnet.id}" }
output "security_group_name" { value = "${openstack_compute_secgroup_v2.security_group.name}" }
output "security_group_id" { value = "${openstack_compute_secgroup_v2.security_group.id}" }
output "keypair_name" { value = "${openstack_compute_keypair_v2.keypair.name}" }
output "server_name" { value = "${openstack_compute_instance_v2.server.name}" }
output "server_id" { value = "${openstack_compute_instance_v2.server.id}" }


resource "openstack_networking_router_v2" "router" {
  name = "router-${var.resource_suffix}"
  external_gateway = "dda079ce-12cf-4309-879a-8e67aec94de4"
}

resource "openstack_networking_network_v2" "network" {
  name = "network-${var.resource_suffix}"
}

resource "openstack_networking_subnet_v2" "subnet" {
  name = "subnet-${var.resource_suffix}"
  network_id = "${openstack_networking_network_v2.network.id}"
  cidr = "10.0.0.0/24"
  dns_nameservers = ["8.8.8.8", "8.8.4.4"]
}

resource "openstack_networking_router_interface_v2" "router_interface" {
  router_id = "${openstack_networking_router_v2.router.id}"
  subnet_id = "${openstack_networking_subnet_v2.subnet.id}"
}

resource "openstack_compute_secgroup_v2" "security_group" {
  name = "security_group-${var.resource_suffix}"
  description = "cloudify manager security group"
  rule {
    from_port = 22
    to_port = 22
    ip_protocol = "tcp"
    cidr = "0.0.0.0/0"
  }
  rule {
    from_port = 80
    to_port = 80
    ip_protocol = "tcp"
    cidr = "0.0.0.0/0"
  }
  rule {
    from_port = 8086
    to_port = 8086
    ip_protocol = "tcp"
    cidr = "0.0.0.0/0"
  }
  rule {
    from_port = 1 
    to_port = 65535
    ip_protocol = "tcp"
    cidr = "${openstack_networking_subnet_v2.subnet.cidr}"
  }
}

resource "openstack_compute_keypair_v2" "keypair" {
  name = "keypair-${var.resource_suffix}"
  public_key = "${file("${var.public_key_path}")}"
}

resource "openstack_networking_floatingip_v2" "floatingip" {
  pool = "GATEWAY_NET"
}

resource "openstack_compute_instance_v2" "server" {
  name = "server-${var.resource_suffix}"
  image_name = "${var.image}"
  flavor_name = "${var.flavor}"
  key_pair = "${openstack_compute_keypair_v2.keypair.name}"
  security_groups = ["${openstack_compute_secgroup_v2.security_group.name}"]
  network {
    uuid = "${openstack_networking_network_v2.network.id}"
  }
  floating_ip = "${openstack_networking_floatingip_v2.floatingip.address}"

  provisioner "remote-exec" {
    inline = [
      "echo hello world"
    ]
    connection {
      type = "ssh"
      user = "centos"
      private_key = "${file("${var.private_key_path}")}"
      timeout = "10m"
    }
  }
}


