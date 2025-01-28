# Web Asset Server
=========

This is a sample attachment server implementation for Specify. This implementation is targeted at Ubuntu distributions but will work with minor modifications on other Linux systems. It is not expected to work without extensive adaptation on Windows systems.

The Specify Collections Consortium is funded by its member institutions. The Consortium website is:  
[http://www.specifysoftware.org](http://www.specifysoftware.org)

**Web Asset Server Copyright © 2021 Specify Collections Consortium.**  
Specify comes with ABSOLUTELY NO WARRANTY. This is free software licensed under the GNU General Public License 2 (GPL2).

    Specify Collections Consortium
    Biodiversity Institute
    University of Kansas
    1345 Jayhawk Blvd.
    Lawrence, KS 66045 USA

## Table of Contents
    
   * [Web Asset Server](#-web-asset-server)
     * [Table of Contents](#table-of-contents)
   * [New Features](#new-features)
   * [Default Rate Restrictions](#default-rate-restrictions)
   * [Deployment](#deployment)
   * [Detailed Docker Installation Instructions](#-detailed-docker-installation-instructions)
     * [Cloning Web Asset Server Source Repository](#cloning-web-asset-server-source-repository)
     * [Configuring Docker Compose .yml](#configuring-docker-compose-yml)
     * [Configuring settings.py](#configuring-settingspy)
     * [Configuring Nginx](#configuring-nginxconf)
     * [Configuring BotBlocker (Optional)](#configuring-botblockeroptional)
   * [Running server.py locally via Python without Nginx](#running-serverpy-locally-via-python-without-nginx)
   * [HTTPS](#https)
   * [Specify Settings](#specify-settings)
     *[Specify6 Settings](#specify-6-settings)
     * [Specify7 Settings](#specify-7-settings)
   * [Compatibility with older versions of Python](#compatibility-with-older-versions-of-python)


## New Features:

**Full Docker Integration**
    - A full docker network ecosystem image database, server and nginx containers defined in .yml file.
    - Improved dockerfiles for nginx and image-server for easy setup.

**Integrated Metadata Management**
   - REST support for reading and writing image metadata. Includes a submodule MetadataTools for editing EXIF metadata.

**Image Asset Organization**
   - Internal MySQL database tracks all imports and allows querying to map a URL back to an original filename.
   - Tiered directory structure based on the first four characters of the MD5 hash to prevent large directory listings.  
     For example, `236586c8a808832c794a525642f5cc42.jpg` is stored in `23/65/236586c8a808832c794a525642f5cc42.jpg`.
   - Prevents duplicate filename imports in a given collection or namespace.

**Redacted Image Support**
   - Supports redacted images with controlled access. Only authenticated users can view redacted images.

**Performance and Security Enhancements**
   - Docker integration with Nginx for optimized performance and enhanced security.
   - Multithreading support with associated Nginx configuration.
   - Nginx rate restriction and CORS policy options for external IPs and Domains.
   - Optional bot and scanner blocker (e.g., Ultimate Bot Blocker).

**Continuous Integration and Testing**
   - Jenkins CI support for automated testing and deployment.
   - Comprehensive test suite to ensure reliability across all features.



## Default Rate Restrictions

* For external users and IP addresses, the current limit is set to 10 requests per minute, with a burst limit of 2.
* No rate limits are imposed on internal users on networks with addresses in the following ranges:
  - 24-bit block: 10.0.0.0
  - 20-bit block: 172.16.0.0
  - 16-bit block: 192.168.0.0

## Deployment:
Copy `docker-compose.template.yml` and `settings.template.py` to their 
respective filenames without 'template' and adjust settings accordingly. Note that you can run the
system without using docker; simply launch the database with the `start_images_development_db.sh` script
and then run the server with "python3 server.py". This is recommended for initial setup and testing.
Note that for testing, you'll need to use a non-privileged port such as 8080. 

Once testing is complete, stop the docker container running the database, and type `docker-compose up -d`
to start the full server.

It is important that the working directory is set to the path containing `server.py`
so that *bottle.py* can find the template files. See [“TEMPLATE NOT FOUND” IN MOD_WSGI/MOD_PYTHON](http://bottlepy.org/docs/dev/faq.html#template-not-found-in-mod-wsgi-mod-python).

# Detailed Docker Installation Instructions
---
The following instructions from [Cloning Web Asset Server Source Repository](#cloning-web-asset-server-source-repository) to [Final docker-compose and setup](#final-docker-compose-and-setup) are for a Docker installation. Instructions for running the server directly without Docker are provided at the bottom.  
If running directly via Python, only the step [Configuring `settings.py`](#configuring-settingspy) needs to be completed after running `git clone git@github.com:calacademy-research/cas-web-asset-server.git`, then skip to [Running server.py locally via python without nginx](#running-serverpy-locally-via-python-without-nginx):.


## Cloning Web Asset Server source repository
Clone this repository.

```shell
git clone git@github.com:calacademy-research/cas-web-asset-server.git
```

## Configuring Docker Compose .yml

Docker in the preferred installation method for Web Asset Server.

An example `docker-compose.template.yml` is provided:

```yaml
services:

  nginx:
    build:
      context: ./
      dockerfile: Dockerfile.nginx
    container_name: bottle-nginx
    ports:
      - '80:80'
      - '443:443'
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
    depends_on:
      - image-server
    logging:
      driver: "json-file"
      options:
        max-size: "1m"
        max-file: "5"
    restart: always

  image-server:
    build:
      context: ./
      dockerfile: Dockerfile.images
    container_name: image-server
    environment:
      - EXTERNAL_IP=institution.org
      - PYTHONUNBUFFERED=1
      - LANG=C.UTF-8
    volumes:
      - ./:/code
    command: ['uwsgi', '--plugin', '/usr/lib/uwsgi/plugins/python312_plugin.so','--ini', 'uwsgi.ini']

    restart: always

  mysql-images:
    restart: unless-stopped
    image: mysql:8
    container_name: mysql-images
    command: "--default-authentication-plugin=mysql_native_password"
    volumes:
      - ./data:/var/lib/mysql:delegated
    environment:
      MYSQL_ROOT_PASSWORD: 'redacted'
      MYSQL_DATABASE: 'images'
      TZ: America/Los_Angeles

    ports:
      - "3306:3306"
    expose:
      - 3306

```
For production use, it is recommended to also add a nginx web server between
the web asset server and the outside world. An example nginx can be found at
[nginx.conf](https://github.com/calacademy-research/cas-web-asset-server/blob/master/nginx.template.conf)
as well as an example docker-compose.yml for a nginx, image-server and image database at [docker-compose.yml](https://github.com/calacademy-research/cas-web-asset-server/blob/master/docker-compose.template.yml).
For development/evaluation, the web asset server can be exposed directly. To do so,
add the following lines to your `docker-compose.yml` right after the `asset-server:` line, 
and comment out the nginx service:

```yaml
    ports:
      - "80:80"
      - "443:443"
```
## Configuring settings.py
Example settings.py at [settings.py](https://github.com/calacademy-research/cas-web-asset-server/blob/master/settings.template.py)
1. Copy settings.template.py to settings.py, 
2. Confirm your server HOST , PORT & SERVER_PROTOCOL match your server settings in docker-compose.yml. 
3. Confirm your SQL_HOST, SQL_PORT, SQL_PASSWORD and SQL_DATABASE match your image db settings.
4. Confirm your BASE_DIR, THUMB_DIR, ORIG_DIR , match your attachments folder setup.
5. Confirm other settings are to your preferences.

## Configuring Nginx.conf:
A nginx is recommended for controlling traffic to your server , a sample template is [nginx.template.conf](https://github.com/calacademy-research/cas-web-asset-server/blob/master/nginx.template.conf)
Copy `nginx.template.conf` to its respective filename and remove 'template'. 
Edit the below nginx map variables to your preferences:
--`$http_user_agent $is_bot`: contains a custom list bot name keywords to block.
--`$remote_addr $is_blocked_ip`: contains a custom list of ip address ranges to block.
--`$limited`: contains whitelisted ip ranges.
--`$http_referer $cors_header`: contains whitelisted http_referrers for CORS policy.

(Optional) For running nginx locally on http:
1. comment out the top server block which redirects port 80 with a 301 code.
2. comment out the lines `ssl_certificate /etc/ssl/certs/name_of_ssl_cert.pem;` and  `ssl_certificate_key /etc/ssl/private/name_of_ssl_cert.key;`.
3. replace the line `listen 443 ssl;` with `listen 80;`, replacing port 80 with any preferred port.

## Configuring botblocker(optional)
Botblocker is a comprehensive add-on that can be used to dynamically block harmful bots from accessing your server. [Github](git@github.com:mitchellkrogza/nginx-ultimate-bad-bot-blocker.git)
1. Copy the templates in `botblocker-settings` for `blacklist-user-agents`, `whitelist-domains.conf` and `whitelist-ips.conf`.
2. Commented out examples are provided in each template. Setup desired whitelist exceptions for allowed ip ranges, user agents and/or domain names.
3. uncomment or add the lines `include /etc/nginx/conf.d/globalblacklist.conf;` and `include /etc/nginx/conf.d/botblocker-nginx-settings.conf;` inside your nginx http brackets.
4. uncomment or add the lines `include /etc/nginx/bots.d/blockbots.conf;` and `include /etc/nginx/bots.d/ddos.conf;` inside your nginx server brackets.
5. add email to Dockerfile.nginx line `RUN echo "00 22 * * * /usr/local/sbin/update-ngxblocker -e youremail@example.org" >> /etc/crontab` for botblocker updates

For ubuntu here is a commented version of the install instructions, which are featured in `Dockerfile.nginx`:

```shell
# Download and install the Nginx Ultimate Bad Bot Blocker 'install-ngxblocker' script
RUN wget https://raw.githubusercontent.com/mitchellkrogza/nginx-ultimate-bad-bot-blocker/master/install-ngxblocker \
    -O /usr/local/sbin/install-ngxblocker \
 && chmod +x /usr/local/sbin/install-ngxblocker

# Run install-ngxblocker and update botlist, telling it to place files in conf.d and bots.d
RUN /usr/local/sbin/install-ngxblocker -x -c /etc/nginx/conf.d -b /etc/nginx/bots.d

# Download and install the setup/update scripts
RUN wget https://raw.githubusercontent.com/mitchellkrogza/nginx-ultimate-bad-bot-blocker/master/setup-ngxblocker \
    -O /usr/local/sbin/setup-ngxblocker \
 && wget https://raw.githubusercontent.com/mitchellkrogza/nginx-ultimate-bad-bot-blocker/master/update-ngxblocker \
    -O /usr/local/sbin/update-ngxblocker \
 && chmod +x /usr/local/sbin/setup-ngxblocker \
 && chmod +x /usr/local/sbin/update-ngxblocker

# run any updates to botblocker
RUN /usr/local/sbin/update-ngxblocker -c /etc/nginx/conf.d -b /etc/nginx/bots.d

# adding custom whitelists to botblocker
COPY botblocker-settings/whitelist-domains.conf botblocker-settings/whitelist-ips.conf botblocker-settings/blacklist-user-agents.conf /etc/nginx/bots.d/

# (Optional) Add a crontab job to periodically update the blocker
RUN echo "00 22 * * * /usr/local/sbin/update-ngxblocker -e youremail@example.org" >> /etc/crontab
```

## Final docker-compose and setup
-- The image-server container runs on an ubuntu 24 docker image.
-- all setup and dependencies are installed automatically in the Dockerfiles. `Dockerfile.nginx` [here](https://github.com/calacademy-research/cas-web-asset-server/blob/master/Dockerfile.nginx) & `Dockerfile.server` [here](cas-web-asset-server).
-- If not using botblocker comment out all lines from the lines 19-42 containing the botblocker install steps
1. Run docker compose.
```shell
docker compose up -d
```
2. (Optional) deploy any sql image db backup by copying your backup .sql file to the mounted folder data/ via `cp image_db_backup.sql data/` and then logging into mysql and running `source /var/lib/mysql/image_db_backup.sql`

---

## Running server.py locally via python without nginx:

-- Copy and setup settings.py. See [Setting up settings.py](#Setting up settings.py)
The dependencies are:

1. *Python* 3.12 is known to work.
1. *Docker* used to deploy the image database.
1. *ImageMagick* for thumbnailing.
1. *ExifTool* for editing exif metadata via the command line.
1. *Metadatatools* submodule at https://github.com/calacademy-research/metadata_tools.git for python methods to edit exif metadata.

To install dependencies
the following commands work on Ubuntu:

```shell
# install ubuntu dependencies
apt-get update && apt-get install -y \
    ca-certificates tzdata wget curl python3-pip python3-setuptools \
    build-essential libffi-dev imagemagick libimage-exiftool-perl \
    gcc-aarch64-linux-gnu uwsgi uwsgi-plugin-python3 python3.12-venv\
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# activate the Metadatatools submodule   
git submodule update --init --recursive
# create venv
python3 -m venv venv
source venv/bin/activate
# install requirements
sudo pip install -r requirements.txt
sudo pip install -r metadata_tools/requirements.txt
## setup the image db docker container (check that the port and password are to your liking)
./start_images_dev.sh
## run the server
python3 server.py
## lastly to check that your setup is working
pytest tests/
```
--The command `python server_ipup.py` automatically updates the host, .yml and settings ip addresses between uses when running server.py locally via python.
---

# HTTPS
The easiest way to add HTTPS support, which is necessary to use the asset server with a Specify 7 server that is using HTTPS, is to place the asset server behind a reverse proxy such as Nginx. This also makes it possible to forego *authbind* and run the asset server on an unprivileged port. The proxy must be configured to rewrite the `web_asset_store.xml` resource to adjust the links therein. An example configuration can be found in [this gist](https://gist.github.com/benanhalt/d43a3fa7bf04edfc0bcdc11c612b2278).

# Specify Settings
## Specify 6 Settings
You will generally want to add the asset server settings to the global Specify preferences so that all of the Specify clients obtain the same configuration.

The easiest way to do this is to open the database in Specify and navigate to the *About* option in the help menu. 

![About Specify](https://user-images.githubusercontent.com/37256050/229819923-fb3a114e-c6fc-4591-8ea2-ae564f4ec099.png)

In the resulting dialog double-click on the **division** name under *System Information* on the right hand side. This will open a properties editor for the global preferences. 

You will need to set four properties to configure access to the asset server:

* `USE_GLOBAL_PREFS` - `true`
* `attachment.key` – `##`
   * Replace `##` with the key from the following location:
     * obtain from asset server `settings.py` file if you have a local installation of 7
     * obtain from `docker-compose.yml` file if you use a Docker deployment
* `attachment.url`  `http://[YOUR_SERVER]/web_asset_store.xml` 
* `attachment.use_path` `false`

If these properties do not already exist, they can be added using the *Add Property* button. 

## Specify 7 Settings

If you are using the [Docker deployment method](https://discourse.specifysoftware.org/t/specify-7-installation-instructions/755#docker-compositions-2), you need to make sure that the `attachment.key` and `attachment.url` match the configuration in Specify 6.

For both the `specify7` and `specify7-worker` sections, you need to make sure that:

- `attachment.key` = `ASSET_SERVER_KEY`
- `attachment.url` = `ASSET_SERVER_URL`

```yml
  specify7:
    restart: unless-stopped
    image: specifyconsortium/specify7-service:v7
    init: true
    volumes:
      - "specify6:/opt/Specify:ro"
      - "static-files:/volumes/static-files"
    environment:
      - DATABASE_HOST=mariadb
      - DATABASE_PORT=3306
      - DATABASE_NAME=specify
      - MASTER_NAME=master
      - MASTER_PASSWORD=master
      - SECRET_KEY=change this to some unique random string
      - ASSET_SERVER_URL=http://host.docker.internal/web_asset_store.xml
      - ASSET_SERVER_KEY=your asset server access key
      - REPORT_RUNNER_HOST=report-runner
      - REPORT_RUNNER_PORT=8080
      - CELERY_BROKER_URL=redis://redis/0
      - CELERY_RESULT_BACKEND=redis://redis/1
      - LOG_LEVEL=WARNING
      - SP7_DEBUG=false
```

If you are using a local installation, in the `settings.py` file, you need to make sure that:

- `attachment.key` = `WEB_ATTACHMENT_KEY`
- `attachment.url` = `WEB_ATTACHMENT_URL`

```py
# The Specify web attachment server URL.
WEB_ATTACHMENT_URL = None

# The Specify web attachment server key.
WEB_ATTACHMENT_KEY = None
```

# Compatibility with older versions of Python

* [Web Asset server for Python 2.7](https://github.com/specify/web-asset-server)
* [Python 2.6 compatibility](https://github.com/specify/web-asset-server#python-2.6-compatibility)



# TODO

  * convert to universal URLS (n2t.net) and database same (images.universal_urls). Our id=42754. http://n2t.
    net/e/n2t_apidoc.html
  * Support invisible watermarks and add API for same
  * support updating all cached resized images, not just thumbnails. 
