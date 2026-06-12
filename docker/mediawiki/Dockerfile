FROM mediawiki:1.43

COPY --from=composer:2 /usr/bin/composer /usr/local/bin/composer

ARG MODERATION_REF=v1.9.3
ARG MW_EXT_REF=REL1_43

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates git unzip; \
    for ext in AbuseFilter SpamBlacklist ConfirmEdit Linter VisualEditor DiscussionTools Nuke OATHAuth ParserFunctions PageForms Elastica CirrusSearch; do \
        if [ ! -d "/var/www/html/extensions/${ext}" ]; then \
            git clone --depth 1 --branch "$MW_EXT_REF" "https://gerrit.wikimedia.org/r/mediawiki/extensions/${ext}" "/var/www/html/extensions/${ext}"; \
            rm -rf "/var/www/html/extensions/${ext}/.git"; \
        fi; \
    done; \
    composer install --no-dev --no-interaction --no-progress --prefer-dist --working-dir=/var/www/html/extensions/Elastica; \
    composer install --no-dev --no-interaction --no-progress --prefer-dist --working-dir=/var/www/html/extensions/CirrusSearch; \
    git clone --depth 1 --branch "$MODERATION_REF" https://github.com/edwardspec/mediawiki-moderation.git /var/www/html/extensions/Moderation; \
    rm -rf /var/www/html/extensions/Moderation/.git; \
    apt-get purge -y --auto-remove git; \
    rm -rf /var/lib/apt/lists/*

COPY mediawiki/extensions/VocomipediaSearch /var/www/html/extensions/VocomipediaSearch
