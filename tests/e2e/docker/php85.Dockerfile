FROM php:8.5-cli
# PHP >= 8.4 no longer bundles ext-imap; the app talks IMAP through webklex/php-imap (pure PHP), so it is not installed here.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libzip-dev libpng-dev libjpeg-dev libicu-dev libxml2-dev libonig-dev git unzip procps default-mysql-client \
 && docker-php-ext-configure gd --with-jpeg \
 && docker-php-ext-install pdo_mysql mbstring zip gd intl xml pcntl \
 && curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer \
 && rm -rf /var/lib/apt/lists/*
