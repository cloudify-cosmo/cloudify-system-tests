
##################################
#replace echo with ctx logger
# add to cloudify-build-system repo
# change the instructions to how to upload jnekins with the instructions of how to upload jenkins using blueprint
# add docs in the blueprints like manager blueprint
##################################

#!/bin/bash 
set -e


function validation
{
    ctx logger info "function validation..."
    echo "JENKINS_MACHINE_TYPE=$JENKINS_MACHINE_TYPE"
        
    if [ ! "$JENKINS_MACHINE_TYPE" == "slave" ] && [ ! "$JENKINS_MACHINE_TYPE" == "master" ]
    then
        echo "JENKINS_MACHINE_TYPE must be one of the options: 'master' or 'slave'"
        exit 1
    fi
    ctx logger info "function validation... done"
}

function install_preparation
{
    ctx logger info "function install_preparation..."
#    echo "$USER ALL=(ALL) NOPASSWD: ALL" > /tmp/sudoers.tmp &&
#    echo $SSH_PASSWORD | sudo -S bash -c 'echo "$(cat /tmp/sudoers.tmp)" | (EDITOR="tee -a" visudo)' &&
    sudo mkdir -p $JENKINS_HOME/jobs &&
    sudo sed -i "1s/.*/127.0.0.1 `hostname`/" /etc/hosts &&
    mkdir -p /tmp/install
    ctx logger info "function install_preparation... done"
}

function install_dependencies
{
    ctx logger info "function install_dependencies..."
    echo "## installing dependencies"
    #sudo timedatectl set-timezone "Asia/Jerusalem" &&
    sudo ntpdate -s time.nist.gov &&
    sudo apt-get update &&
    echo "# installing libraries"
    sudo apt-get -y install build-essential tofrodos git subversion python-software-properties python-setuptools python-dev python-pip unzip sshpass &&
    echo "# installing java"
    sudo apt-get -y install openjdk-7-jdk &&
    sudo pip install boto==2.36.0 &&
    sudo pip install s3cmd==1.5.2 &&
    sudo pip install virtualenv==13.1.2 &&
    sudo pip install serv==0.1.1 &&
    sudo pip install awscli==1.10.22 &&
    sudo pip install python-openstackclient==2.4.0
    ctx logger info "function install_preparation... done"
}

function user_configuration
{
    ctx logger info "function user_configuration..."
    echo "$user_name:$user_name" | sudo chpasswd &&
    sudo bash -c "grep 'alias ll=' /etc/bash.bashrc || echo 'alias ll=\"ls -l\"' >> /etc/bash.bashrc" &&
    sudo chown $user_name:$user_name -R $JENKINS_HOME
    ctx logger info "function user_configuration... done"
}

function install_dependencies_under_user_jenkins
{
    ctx logger info "function install_dependencies_under_user_jenkins..."
    echo "## installing virtualbox"
    sudo apt-get install -y virtualbox &&

    echo "## installing vagrant"
    #wget https://releases.hashicorp.com/vagrant/1.6.5/vagrant_1.6.5_x86_64.deb -P /tmp/install && sudo dpkg -i /tmp/install/vagrant_1.6.5_x86_64.deb &&
    wget https://releases.hashicorp.com/vagrant/1.8.4/vagrant_1.8.4_x86_64.deb --no-check-certificate -P /tmp/install && sudo dpkg -i /tmp/install/vagrant_1.8.4_x86_64.deb &&
    #sudo -H -u $user_name bash -c 'vagrant plugin install vagrant-aws --plugin-version 0.6.0' &&
    #sudo -H -u $user_name bash -c 'vagrant plugin install vagrant-openstack-plugin --plugin-version 0.12.0' &&
    #sudo -H -u $user_name bash -c 'vagrant plugin install vagrant-scp --plugin-version 0.4.3' &&
    sudo -H -u $user_name bash -c 'vagrant plugin install vagrant-aws --plugin-version 0.7.2' &&
    sudo -H -u $user_name bash -c 'vagrant plugin install vagrant-openstack-plugin --plugin-version 0.12.0' &&
    sudo -H -u $user_name bash -c 'vagrant plugin install vagrant-scp --plugin-version 0.5.7' &&

    echo "## installing packer"
    wget -q  https://releases.hashicorp.com/packer/0.10.0/packer_0.10.0_linux_amd64.zip -P /tmp/install &&
    sudo unzip -o /tmp/install/packer_0.10.0_linux_amd64.zip -d /usr/bin/ &&

    echo "## installing node"
    sudo -H -u $user_name bash -c 'curl -o- https://raw.githubusercontent.com/creationix/nvm/v0.30.1/install.sh | bash' &&
    sudo bash -c "grep 'export NVM_DIR=' /etc/bash.bashrc || echo 'export NVM_DIR=\"/var/lib/jenkins/.nvm\"' >> /etc/bash.bashrc" &&
    sudo bash -c "grep '/nvm.sh' /etc/bash.bashrc || echo '[ -s \"\$NVM_DIR/nvm.sh\" ] && . \"\$NVM_DIR/nvm.sh\"' >> /etc/bash.bashrc"

    #echo "## installing vault"
#    wget https://releases.hashicorp.com/vault/0.5.2/vault_0.5.2_linux_amd64.zip -P /tmp/install &&
#    sudo unzip /tmp/install/vault_0.5.2_linux_amd64.zip -d /usr/local/bin/
    ctx logger info "function install_dependencies_under_user_jenkins... done"
}

function install_credentials
{
    ctx logger info "function install_credentials..."
    echo "## installing credentials"

    ctx logger info "function install_credentials...1"
    sudo chown $USER -R $JENKINS_HOME
    mkdir -p $JENKINS_HOME/.ssh/aws
    ctx logger info "function install_credentials...2"
    if [ -d  /opt/backup/cloudify-build-system ]; then sudo rm -rf /opt/backup/cloudify-build-system; fi
    #sudo mkdir -p /opt/backup/cloudify-build-system
    ctx logger info "function install_credentials...3"
    git config --global user.name "opencm"
    ctx logger info "function install_credentials...3.1"
    git config --global user.email limor@gigaspaces.com
    ctx logger info "function install_credentials...3.2"
    git clone https://$GITHUB_USERNAME:$GITHUB_PASSWORD@github.com/cloudify-cosmo/cloudify-build-system.git
    ctx logger info "function install_credentials...3.3"
    sudo mkdir -p /opt/backup
    sudo mv ./cloudify-build-system /opt/backup/

    ctx logger info "function install_credentials...4"
    pushd /opt/backup/cloudify-build-system
        ctx logger info "function install_credentials...4.1"
        sudo virtualenv env &&
        ctx logger info "function install_credentials...4.2"
        source env/bin/activate &&
        ctx logger info "function install_credentials...4.3"
        sudo /opt/backup/cloudify-build-system/env/bin/pip install .
        ctx logger info "function install_credentials...4.4"
    popd
    ctx logger info "function install_credentials...5"
    crt vault get -u 'http://172.31.42.24:8200' -t $VAULT_TOKEN -p 'secret/builds' -d $JENKINS_HOME'/jobs/credentials.sh' -v &&
    sudo fromdos $JENKINS_HOME/jobs/credentials.sh &&
    ctx logger info "function install_credentials...6"
    fields_info="id_rsa,secret/builds_files/jenkins_ssh_rsa,$JENKINS_HOME/.ssh/id_rsa:"`
        		`"id_rsa_pub,secret/builds_files/jenkins_ssh_rsa_pub,$JENKINS_HOME/.ssh/id_rsa.pub:"`
    			`"vagrant_build,secret/builds_files/jenkins_ssh_aws_vbuild,$JENKINS_HOME/.ssh/aws/vagrant_build.pem:"`
    			`"vagrant_centos_build,secret/builds_files/jenkins_ssh_aws_vcbuild,$JENKINS_HOME/.ssh/aws/vagrant_centos_build.pem:"`
    			`"windows_agent_packager,secret/builds_files/jenkins_ssh_aws_vwbuild,$JENKINS_HOME/.ssh/aws/windows_agent_packager.pem"

    ctx logger info "function install_credentials...7"
    crt vault readtofiles -u 'http://172.31.42.24:8200' -t $VAULT_TOKEN -i $fields_info &&
    ctx logger info "function install_credentials...8"
    sudo chown $user_name:$user_name -R $JENKINS_HOME
    ctx logger info "function install_credentials...8.1"
    sudo chown $user_name:$user_name -R /opt/backup
    ctx logger info "function install_credentials...8.2"
    ctx logger info `echo $user_name`
    ctx logger info `echo $JENKINS_HOME`
    ctx logger info "function install_credentials...9"
    ssh-keyscan -H github.com >> ~/known_hosts
    ctx logger info "function install_credentials...9.1"
    sudo mv ~/known_hosts $JENKINS_HOME/.ssh/known_hosts
    ctx logger info "function install_credentials...9.2"
    sudo -H -u $user_name bash -c 'chmod 700 ~/.ssh/aws/'
    ctx logger info "function install_credentials... done"
}

function install_jenkins
{
    ctx logger info "function install_jenkins..."
    echo "## installing jenkins"
    sudo apt-get update &&
    pushd /tmp/install
      echo "installing jenkins"
      sudo wget -q http://pkg.jenkins-ci.org/debian/binary/jenkins_1.631_all.deb &&
      sudo apt-get -y install daemon &&
      sudo dpkg -i /tmp/install/jenkins_1.631_all.deb &&
    popd

    sudo chown $user_name:$user_name -R /usr/share/jenkins &&
    sudo chown $user_name:$user_name -R /var/cache/jenkins &&
    sudo chown $user_name:$user_name -R $JENKINS_HOME &&

    sudo -H -u $user_name bash -c 'mkdir -p ~/backup' &&


    echo "## changing default port"
    sudo sed -i "s/.*HTTP_PORT=.*/HTTP_PORT=${JENKINS_PORT}/g" /etc/default/jenkins
    ctx logger info "function install_jenkins... done"
}

function restore_configuration
{
    ctx logger info "function restore_configuration..."
    echo "## restoring jenkins configuration"
    # installing git lfs
    if [ -d /tmp/install/git-lfs-1.1.2 ]
    then
        sudo rm -rf /tmp/install/git-lfs-1.1.2
    fi
    wget -q https://github.com/github/git-lfs/releases/download/v1.1.2/git-lfs-linux-amd64-1.1.2.tar.gz -P /tmp/install &&
    pushd /tmp/install
        tar -zxvf git-lfs-linux-amd64-1.1.2.tar.gz &&
        pushd git-lfs-1.1.2
            chmod +x install.sh &&
            sudo ./install.sh &&
            sudo git lfs install --skip-smudge
        popd
    popd

    #sudo -H -u $user_name bash -c 'fromdos ~/jobs/credentials.sh && source ~/jobs/credentials.sh && \
    #sudo -H -u $user_name bash -c 'if [ -d  /opt/backup/cloudify-build-system ]; then rm -rf /opt/backup/cloudify-build-system ; fi ; \
    #git clone https://$GITHUB_USERNAME:$GITHUB_PASSWORD@github.com/cloudify-cosmo/cloudify-build-system.git /opt/backup/cloudify-build-system && \
    echo "##copy jenkins backup from cloudify-build-system/jenkins/backup/backup.tar.gz to /var/lib"
    sudo -H -u $user_name bash -c 'cd /opt/backup/cloudify-build-system && git lfs pull && \
    tar -xzvf /opt/backup/cloudify-build-system/jenkins/backup/backup.tar.gz -C /var/lib'
    sudo chown $user_name:$user_name -R $JENKINS_HOME

    #sudo service jenkins stop && sudo service jenkins start
    ctx logger info "function restore_configuration... done"
}

function install_jenkins_slave()
{
    ctx logger info "function install_jenkins_slave..."
    echo "## Installing jenkins slave"
    . /var/lib/jenkins/jobs/credentials.sh
    jenkins_slave_home=$JENKINS_HOME/jobs/jenkins-slave

    if [ ! -f $jenkins_slave_home/swarm-client.jar ]; then
        sudo -H -u $user_name bash -c 'mkdir -p '$jenkins_slave_home

        pushd $jenkins_slave_home
            sudo -H -u $user_name bash -c 'wget http://repo.jenkins-ci.org/releases/org/jenkins-ci/plugins/swarm-client/2.0/swarm-client-2.0-jar-with-dependencies.jar -O swarm-client.jar'
            sudo serv generate \
                --name jenkins-slave \
                --deploy \
                --start \
                --overwrite \
                --user $user_name \
                --group $user_name \
                --chdir $PWD \
                --var HOME=$JENKINS_HOME \
                --var USER=$user_name \
                /usr/bin/java --args "\
                    -jar swarm-client.jar \
                    -master $JENKINS_MASTER_URL \
                    -username $JENKINS_USR \
                    -password $JENKINS_PWD \
                    -executors 10 \
                    -mode normal \
                    -labels swarm \
                    -name `hostname`"
        popd
    fi
    sudo chown $user_name:$user_name -R $JENKINS_HOME
    sudo service jenkins-slave restart
    #/var/log/upstart/jenkins-slave.log
    ctx logger info "function install_jenkins_slave... done"
}

function get_installed_versions
{
    ctx logger info "function get_installed_versions..."
    echo "## get jenkins version"
    echo "vagrant version:"
    sudo -H -u $user_name bash -c 'vagrant -v'
    echo "virtualbox version:"
    sudo -H -u $user_name bash -c 'vboxmanage --version'
    echo "get jenkins version:"
    sudo -H -u $user_name bash -c 'java -jar /var/cache/jenkins/war/WEB-INF/jenkins-cli.jar -s http://`hostname`:8080 version --username $JENKINS_USR --password $JENKINS_PWD'
    echo "jenkins installed plugins list:"
    sudo -H -u $user_name bash -c 'java -jar /var/cache/jenkins/war/WEB-INF/jenkins-cli.jar -s http://`hostname`:8080 list-plugins --username $JENKINS_USR --password $JENKINS_PWD'
    ctx logger info "function get_installed_versions... done"
}


ctx logger info "start..."
export JENKINS_HOME='/var/lib/jenkins'
export user_name=$JENKINS_USER_NAME

validation &&

if [ "$JENKINS_MACHINE_TYPE" == "slave" ]; then
    if [ "$MASTER_HOST_IP" == "localhost" ]; then
        MASTER_IP=`hostname -I`
        MASTER_HOST_IP=$(echo ${MASTER_IP})
    fi
    JENKINS_MASTER_URL="http://$MASTER_HOST_IP:$JENKINS_PORT"
    echo "SLAVE_ON_MASTER=$SLAVE_ON_MASTER"
    echo "JENKINS_MASTER_URL=$JENKINS_MASTER_URL"
fi

if [ "$JENKINS_MACHINE_TYPE" == "master" ] || [ "$JENKINS_MACHINE_TYPE" == "slave" ] && [ "$SLAVE_ON_MASTER" != "true" ]; then
    install_preparation &&
    install_dependencies 
fi

if [ "$JENKINS_MACHINE_TYPE" == "master" ]; then
    install_jenkins
fi

if [ "$JENKINS_MACHINE_TYPE" == "slave" ] && [ "$SLAVE_ON_MASTER" != "true" ]; then
    sudo addgroup $user_name && sudo useradd $user_name -d $JENKINS_HOME --shell /bin/bash -g $user_name
fi

if [ "$JENKINS_MACHINE_TYPE" == "master" ] || [ "$JENKINS_MACHINE_TYPE" == "slave" ] && [ "$SLAVE_ON_MASTER" != "true" ]; then
    user_configuration &&
    install_dependencies_under_user_jenkins
    install_credentials
fi

if [ "$JENKINS_MACHINE_TYPE" == "master" ]; then
     restore_configuration
fi

if [ "$JENKINS_MACHINE_TYPE" == "slave" ]; then
    install_jenkins_slave
fi
ctx logger info "start... done"