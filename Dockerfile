FROM php:8.5-apache

# ext-imap is gone in PHP 8.4+; the app talks IMAP through webklex/php-imap (pure PHP).
RUN apt-get update \
 && apt-get install -y --no-install-recommends libzip-dev libpng-dev libjpeg-dev libicu-dev libxml2-dev libonig-dev unzip git \
 && docker-php-ext-configure gd --with-jpeg \
 && docker-php-ext-install pdo_mysql mbstring zip gd intl xml pcntl \
 && a2enmod rewrite headers \
 && sed -ri 's#/var/www/html#/var/www/html/public#g' /etc/apache2/sites-available/*.conf /etc/apache2/apache2.conf /etc/apache2/conf-available/*.conf \
 && printf 'upload_max_filesize=64M\npost_max_size=64M\nmemory_limit=512M\n' > /usr/local/etc/php/conf.d/onedesk.ini \
 && rm -rf /var/lib/apt/lists/*
COPY --from=composer:2 /usr/bin/composer /usr/local/bin/composer

WORKDIR /var/www/html
COPY . .
RUN composer install --no-dev --optimize-autoloader --no-scripts --no-interaction --no-security-blocking \
 && mkdir -p storage/framework/cache storage/framework/sessions storage/framework/views storage/logs bootstrap/cache \
 && chown -R www-data:www-data storage bootstrap/cache public/js/builds public/css/builds 2>/dev/null || true

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
VOLUME ["/var/www/html/storage"]
EXPOSE 80
ENTRYPOINT ["entrypoint.sh"]
CMD ["apache2-foreground"]
