# OneDesk

Self-hosted help desk and shared mailbox. OneDesk is a fork of [FreeScout](https://github.com/freescout-help-desk/freescout), maintained by [BMS Suisse](https://github.com/bmsuisse) and licensed under the [AGPL-3.0](LICENSE).

## Stack

- Laravel 12, PHP 8.2 - 8.5 (tested on 8.5)
- MySQL / MariaDB (PostgreSQL is supported by the code but not covered by the tests)
- Symfony Mailer for outgoing mail: SMTP, sendmail, PHP `mail()`, OAuth2 (XOAUTH2)
- Parallel IMAP fetching: one process per mailbox (`APP_FETCH_PARALLEL`, default 4, `1` = sequential)

## Install

```bash
git clone https://github.com/bmsuisse/onedesk.git
cd onedesk
composer install --no-dev
cp .env.example .env && php artisan key:generate
```

Then open the site in a browser and follow the web installer, or run `php artisan migrate --force`. Point the web server at `public/`, and add a cron entry that runs `php artisan schedule:run` every minute.

`tools/install.sh` automates this on Ubuntu, and `tools/update.sh` updates an existing installation.

## Updating

Back up the database, pull the new release, run `composer install --no-dev` and `php artisan migrate --force`, then `php artisan freescout:clear-cache`. The built-in updater in the admin panel downloads releases from this repository.

## Configuration

Settings live in `.env` (see `.env.example`). Notable ones:

| Variable | Purpose |
|---|---|
| `APP_URL` | Public URL. Requests for other hosts are refused unless listed in `APP_TRUSTED_HOSTS`. |
| `APP_FETCH_PARALLEL` | Number of mailboxes fetched at once. |
| `APP_TRUSTED_PROXIES` | Reverse proxies whose `X-Forwarded-*` headers are trusted. |
| `APP_CLOUDFLARE_IS_USED` | Use `CF-Connecting-IP`, but only for requests coming from Cloudflare or a trusted proxy. |
| `ONEDESK_MODULES_API` | Optional module directory / license server. Empty by default (disabled). |

Outgoing "TLS" encryption requires STARTTLS and refuses to send in clear text if the server does not offer it.

## Modules

OneDesk keeps FreeScout's module system, but it runs on Laravel 12. Modules written for FreeScout (Laravel 5.5) will not work until they are ported.

## Tests

Docker is the only requirement.

```bash
tests/e2e/run.sh test              # real freescout:fetch-emails against Dovecot + MariaDB (PHP 8.5; PHPV=81 for 8.1)
bash tests/e2e/suites/send.sh      # every outgoing mail path against a mail sink
tests/e2e/run.sh profile 1         # sampling profile of one mailbox fetch
```

`tests/e2e/web.py` is a browser smoke test of the web UI. Known issue: the e2e case `folders` fails intermittently (killed fetch runs leave child processes running).

## Security

See [SECURITY.md](SECURITY.md).

## Credits

OneDesk is based on FreeScout by its contributors. FreeScout's copyright notices and the AGPL-3.0 license are kept in [LICENSE](LICENSE).
