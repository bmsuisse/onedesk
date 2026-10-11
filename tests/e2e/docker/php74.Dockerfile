FROM php:7.4-cli
RUN printf 'deb http://archive.debian.org/debian bullseye main\ndeb http://archive.debian.org/debian-security bullseye-security main\n' > /etc/apt/sources.list \
 && apt-get -o Acquire::Check-Valid-Until=false update \
 && apt-get install -y --fix-missing libzip-dev libpng-dev libjpeg-dev libicu-dev libc-client-dev libkrb5-dev libxml2-dev libonig-dev git unzip procps default-mysql-client \
 && docker-php-ext-configure imap --with-kerberos --with-imap-ssl \
 && docker-php-ext-configure gd --with-jpeg \
 && docker-php-ext-install pdo_mysql mbstring zip gd intl imap xml pcntl \
 && curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer
# Sampling profiler for `run.sh profile` (Excimer: low overhead, wall-clock timer; needs PHP >= 7.2).
RUN (pecl install excimer-1.1.1 || pecl install excimer) && docker-php-ext-enable excimer
