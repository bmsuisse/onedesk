# OneDesk

> **OneDesk is a fork of [FreeScout](https://github.com/freescout-help-desk/freescout)** maintained by [BMS Suisse](https://github.com/bmsuisse). It is licensed under the [AGPL-3.0](LICENSE), like the original. FreeScout is copyright of its respective authors. Changes in this fork: parallel mailbox fetching (`APP_FETCH_PARALLEL`) and bug fixes. See the git history for details.

## What OneDesk improves (mail fetching)

- **Parallel fetching, on by default:** one child process per mailbox, 4 at a time (`APP_FETCH_PARALLEL=4`; set `1` to fetch sequentially). No global sleep ramp in this mode. E2E: 1,730 mails across 20 mailboxes in ~21 s.
- **Less work per mail:** about half the DB queries per imported mail (38.7 down to roughly 18-23), lazy parsing of message bodies, bunch-wise processing with lower memory use.
- **Mail is no longer lost or duplicated**, among others:
  - unseen paging drift that skipped mails
  - Bcc/To fan-out into several mailboxes
  - parallel races (message-id, attachment files, conversation numbers)
  - mails killed mid-import
  - failed extra-mailbox copies
  - same Message-ID twice in one bunch
- **Runs on current PHP:** the e2e suite (fetching all cases + web smoke) is green on **PHP 8.5** as well as 7.4 (`PHPV=85 tests/e2e/run.sh up quick`). Fixed for PHP >= 8.4, which no longer ships ext-imap: sender addresses written as `addr@host (Comment)` (typical for bounces) were dropped.
- **More robust parsing:** multipart without boundary, nested single-child multipart, boundary text inside bodies, invalid UTF-8 plain-text bodies, huge/cyclic garbage mails.
- **Honest monitoring:** failed folder counts/pages no longer record the run as successful, so the fetch monitor can alert. Transient DB errors are retried instead of marking the mail Seen.
- **Tests:** `tests/e2e/run.sh test` runs the real `freescout:fetch-emails` against Dovecot and MariaDB in Docker with generated, realistic mail (attachments, malformed MIME, fan-out, mailing lists, bounces, kills) and checks exact counts.

Known open: [#2](https://github.com/bmsuisse/onedesk/issues/2) (IMAP body fetch marks mail Seen before import), [#8](https://github.com/bmsuisse/onedesk/issues/8) (poison messages are retried every run). Idle-refresh speed with very many mailboxes is not yet measured or optimised.

---

# Free Self-Hosted Zendesk & Help Scout Alternative

<div align="center">

<img src="https://raw.githubusercontent.com/freescout-help-desk/freescout/master/public/img/logo-300.png" width="180" height="180" />

</div>

**FreeScout** is the super lightweight and powerful free open source help desk and shared inbox built with PHP (Laravel framework). Now you can enjoy free Zendesk & Help Scout without giving up privacy or locking yourself into a service you don't control. FreeScout has been developed from scratch and does not use any copyrighted Help Scout or Zendesk materials.

If you want to support the project feel free to **star this repository**. It helps to increase the visibility of the project and let people know that it is valuable. Thanks for your support!

![FreeScout](https://freescout-helpdesk.github.io/img/screenshots/screenshot.png)

## Table of Contents
   * [Demo](#demo)
   * [Features](#features)
   * [Mobile Apps](#mobile-apps)
   * [Requirements](#requirements)
   * [Installation](#installation)
   * [Images & One-Click Installs](#images--one-click-installs)
   * [Modules](#modules)
   * [Tools & Integrations](#tools--integrations)
   * [News & Updates](#news--updates)
   * [Contributing](#contributing)
   * [Screenshots](#screenshots)

## Demo

**[Live Demo](https://demo.freescout.net)**

## Features

  * Omnichannel — FreeScout centralizes in one place all customer conversations received by email, [WhatsApp](https://freescout.net/whatsapp/), Telegram, Facebook, Slack, Live Chat and more.
  * [AI-powered](https://github.com/freescout-help-desk/AiIntegration) and super efficient.
  * Unlimited support agents, tickets, mailboxes, etc.
  * [Secure](https://freescout.net/security) by design.
  * Mobile-friendly.
  * Multilingual (translated into 33 languages).
  * Seamless email integration (via SMTP, IMAP, POP3, etc).
  * Modern OAuth authentication for Microsoft Office 365 and Google Workspace.
  * Native [S3 storage](https://github.com/freescout-help-desk/S3Storage) support.
  * Fully supports screen readers (for visually impaired).
  * Web installer & updater.
  * Starred conversations.
  * Push notifications.
  * Following conversations.
  * Auto replies.
  * Internal notes.
  * Forwarding / Merging / Moving conversations.
  * Phone conversations.
  * Sending new conversations to multiple recipients at once.
  * Collision detection – notice is shown when two agents open the same conversation.
  * Automatic refreshing of the conversations list without the need to reload the page.
  * Pasting screenshots from the clipboard into the reply area.
  * Flexible notifications for user agents.
  * Open tracking.
  * Powerful search.

A full list of features is available [here](https://freescout.net/#custom_html-3).

Need anything else? [Suggest features](https://freescout.net/request-feature/).

## Mobile Apps

Mobile apps support the same functionality and modules as the web version of your FreeScout installation. Both support agents and administrators can use mobile apps.

<a href="https://freescout.net/android-app/" target="_blank" rel="nofollow"><img alt="Android App" src="https://freescout-helpdesk.github.io/img/apps/android.png" width="200px" /></a> <a href="https://freescout.net/ios-app/" target="_blank" rel="nofollow"><img alt="iOS App" src="https://freescout-helpdesk.github.io/img/apps/ios.png?v=1" width="200px" /></a>

[MacOS Menu Bar App](https://github.com/jonalaniz/scouter)

## Requirements

FreeScout is a pure PHP/MySQL application, so it can be easily deployed even on a [shared hosting](https://github.com/freescout-help-desk/freescout/wiki/Choosing-a-Server).

  * Nginx / Apache / IIS
  * PHP 7.4 - 8.x
  * MySQL 5.0+ / MariaDB 5.0+ / PostgreSQL

There are no minimum system requirements (CPU / RAM) – FreeScout will run on any system.

## Installation

[Installation Guide](https://github.com/freescout-help-desk/freescout/wiki/Installation-Guide)

## Images & One-Click Installs

* [Docker Image](https://freescout.net/docker/)
* [Pikapods](https://freescout.net/pikapods/) — Open-source apps hosting (Fully managed)
* [Zenith](https://freescout.net/zenith/) — Open-source apps hosting (Fully managed)
* [Hostinger](https://freescout.net/hostinger/) — VPS with automatic backups included
* [Softaculous](http://www.softaculous.com/apps/customersupport/FreeScout) — cPanel, Plesk, ISPmanager, H-Sphere, DirectAdmin, InterWorx
* [Fantastico](http://ff3.netenberg.com/visitors/scripts/freescout/view) — cPanel, DirectAdmin, ISP Manager, ISP Config
* [Cloudron](https://cloudron.io/store/net.freescout.cloudronapp.html)
* [Ubuntu](https://github.com/freescout-help-desk/freescout/wiki/Installation-Guide#interactive-installation-bash-script-ubuntu) — Bash script

[More one-click installs…](https://freescout.net/one-click-installs/)

## Modules

* [Official Modules](https://freescout.net/modules/)
* [Community Modules](https://freescout.net/community-modules/)

## Tools & Integrations
  
  * [API](https://api-docs.freescout.net/)
  * [Migrate to FreeScout](http://freescout.net/migrate/) (from any help desk)
  * [Zapier](https://freescout.net/zapier/)
  * [Make](https://freescout.net/make-integration/) (Integromat)

## News & Updates

Don't miss news, updates and new modules!

[Email Newsletter](https://freescout.net/subscribe/) | [Facebook](https://freescout.net/facebook/) | [Twitter](https://freescout.net/twitter/) | [YouTube](https://freescout.net/youtube/) | [Telegram](https://freescout.net/telegram/) | [RSS](https://freescout.net/feed/)

## Contributing

* [Support the project by leaving a feedback](https://github.com/freescout-help-desk/freescout/issues/288)
* [Development Guide](https://github.com/freescout-help-desk/freescout/wiki/Development-Guide)
* [Todo list](https://github.com/freescout-help-desk/freescout/labels/help%20wanted)
* [Translate](https://github.com/freescout-help-desk/freescout/wiki/Translate)

## Screenshots

Dashboard:

![Dashboard](https://freescout-helpdesk.github.io/img/screenshots/dashboard.png)

Conversation:

![Conversation](https://freescout-helpdesk.github.io/img/screenshots/conversation.png)

Drafting reply with AI:

![Mailbox connection settings page](https://freescout-helpdesk.github.io/img/screenshots/draft-reply-with-ai.png)

Notifications:

![Notifications](https://freescout-helpdesk.github.io/img/screenshots/notifications.png)

Push notification:

![Push notification](https://freescout-helpdesk.github.io/img/screenshots/push.png)

Web installer:

![Web installer](https://freescout-helpdesk.github.io/img/screenshots/installer.png)

Login page:

![Login page](https://freescout-helpdesk.github.io/img/screenshots/freescout-login.png)