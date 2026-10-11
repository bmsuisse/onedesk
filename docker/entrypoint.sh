#!/bin/sh
# Starts the scheduler and the queue worker next to Apache. Needs APP_KEY, APP_URL and the DB_* variables.
set -e
cd /var/www/html
# One-off commands (artisan key:generate --show, composer, ...) skip the startup work.
[ "$1" = "apache2-foreground" ] || exec "$@"
[ -n "$APP_KEY" ] || { echo "APP_KEY is required (e.g. docker run --rm onedesk php artisan key:generate --show)"; exit 1; }
chown -R www-data:www-data storage bootstrap/cache
rm -f bootstrap/cache/*.php
until php -r 'try { new PDO("mysql:host=".getenv("DB_HOST").";port=".(getenv("DB_PORT")?:3306).";dbname=".getenv("DB_DATABASE"), getenv("DB_USERNAME"), getenv("DB_PASSWORD")); } catch (Throwable $e) { exit(1); }'; do echo "waiting for the database..."; sleep 2; done
su -s /bin/sh www-data -c "php artisan package:discover --ansi && php artisan migrate --force"
# Cron: every minute. Queue worker: restarted if it exits.
su -s /bin/sh www-data -c 'while true; do php artisan schedule:run >/dev/null 2>&1; sleep 60; done' &
su -s /bin/sh www-data -c 'while true; do php artisan queue:work --queue=emails,default --sleep=5 --tries=3 >/dev/null 2>&1; sleep 5; done' &
exec "$@"
