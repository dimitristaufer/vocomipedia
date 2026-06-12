<?php
# Skeleton only. Generate a real LocalSettings.php through the MediaWiki
# installer, then merge these Vocomipedia-specific settings.

$wgSitename = "Vocomipedia";
$wgMetaNamespace = "Vocomipedia";
$wgServer = "https://vocomipedia.com";
$wgLogos = [
    '1x' => "$wgResourceBasePath/resources/assets/vocomi-logo-135.png",
    'icon' => "$wgResourceBasePath/resources/assets/vocomi-logo-135.png",
];
$wgLogo = "$wgResourceBasePath/resources/assets/vocomi-logo-135.png";
$wgEnableEmail = true;
$wgEnableUserEmail = true;
$wgEmailAuthentication = true;
error_reporting( E_ALL & ~E_DEPRECATED & ~E_USER_DEPRECATED );

# Real namespaces keep generated content, deck indexes, policies, and project
# documentation separate from ordinary mainspace pages.
defined( 'NS_VOCOMIPEDIA_ITEM' ) || define( 'NS_VOCOMIPEDIA_ITEM', 3000 );
defined( 'NS_VOCOMIPEDIA_ITEM_TALK' ) || define( 'NS_VOCOMIPEDIA_ITEM_TALK', 3001 );
defined( 'NS_VOCOMIPEDIA_DECK' ) || define( 'NS_VOCOMIPEDIA_DECK', 3002 );
defined( 'NS_VOCOMIPEDIA_DECK_TALK' ) || define( 'NS_VOCOMIPEDIA_DECK_TALK', 3003 );
defined( 'NS_VOCOMIPEDIA_POLICY' ) || define( 'NS_VOCOMIPEDIA_POLICY', 3004 );
defined( 'NS_VOCOMIPEDIA_POLICY_TALK' ) || define( 'NS_VOCOMIPEDIA_POLICY_TALK', 3005 );

$wgExtraNamespaces[NS_VOCOMIPEDIA_ITEM] = 'Item';
$wgExtraNamespaces[NS_VOCOMIPEDIA_ITEM_TALK] = 'Item_talk';
$wgExtraNamespaces[NS_VOCOMIPEDIA_DECK] = 'Deck';
$wgExtraNamespaces[NS_VOCOMIPEDIA_DECK_TALK] = 'Deck_talk';
$wgExtraNamespaces[NS_VOCOMIPEDIA_POLICY] = 'Policy';
$wgExtraNamespaces[NS_VOCOMIPEDIA_POLICY_TALK] = 'Policy_talk';
$wgContentNamespaces[] = NS_VOCOMIPEDIA_ITEM;
$wgContentNamespaces[] = NS_VOCOMIPEDIA_DECK;
$wgContentNamespaces[] = NS_VOCOMIPEDIA_POLICY;
$wgNamespacesToBeSearchedDefault[NS_MAIN] = false;
$wgNamespacesToBeSearchedDefault[NS_VOCOMIPEDIA_ITEM] = true;
$wgNamespacesToBeSearchedDefault[NS_VOCOMIPEDIA_DECK] = true;
$wgNamespacesToBeSearchedDefault[NS_VOCOMIPEDIA_POLICY] = true;
$wgNamespacesWithSubpages[NS_VOCOMIPEDIA_ITEM] = true;
$wgNamespacesWithSubpages[NS_VOCOMIPEDIA_ITEM_TALK] = true;
$wgNamespacesWithSubpages[NS_VOCOMIPEDIA_DECK] = true;
$wgNamespacesWithSubpages[NS_VOCOMIPEDIA_DECK_TALK] = true;
$wgNamespacesWithSubpages[NS_VOCOMIPEDIA_POLICY] = true;
$wgNamespacesWithSubpages[NS_VOCOMIPEDIA_POLICY_TALK] = true;

# Read-only anonymous launch is the safest default.
$wgGroupPermissions['*']['edit'] = false;
$wgGroupPermissions['*']['createaccount'] = true;
$wgGroupPermissions['user']['edit'] = true;
$wgGroupPermissions['user']['move'] = false;
$wgGroupPermissions['user']['move-subpages'] = false;
$wgGroupPermissions['user']['movefile'] = false;

# Production hardening. Moderation remains the last-loaded extension.
wfLoadExtension( 'AbuseFilter' );
wfLoadExtension( 'SpamBlacklist' );
wfLoadExtension( 'ConfirmEdit' );
wfLoadExtension( 'ConfirmEdit/QuestyCaptcha' );
wfLoadExtension( 'Linter' );
wfLoadExtension( 'VisualEditor' );
wfLoadExtension( 'DiscussionTools' );
wfLoadExtension( 'Nuke' );
wfLoadExtension( 'OATHAuth' );
wfLoadExtension( 'ParserFunctions' );
wfLoadExtension( 'PageForms' );
wfLoadExtension( 'VocomipediaSearch' );

if ( file_exists( "$IP/extensions/Elastica/extension.json" ) && file_exists( "$IP/extensions/CirrusSearch/extension.json" ) ) {
    wfLoadExtension( 'Elastica' );
    wfLoadExtension( 'CirrusSearch' );
    $wgSearchType = 'CirrusSearch';
    $wgCirrusSearchServers = [ [ 'host' => 'elasticsearch', 'port' => 9200 ] ];
    $wgCirrusSearchConnectionAttempts = 3;
}

$wgCaptchaQuestions = [
    'What app is this wiki for?' => 'Vocomi',
];
$wgCaptchaTriggers['createaccount'] = true;
$wgCaptchaTriggers['addurl'] = true;
$wgCaptchaTriggers['badlogin'] = true;
$wgCaptchaTriggers['create'] = true;
$wgCaptchaTriggers['edit'] = false;

$wgGroupPermissions['bureaucrat']['userrights'] = true;
$wgGroupPermissions['*']['viewedittab'] = true;
$wgGroupPermissions['user']['viewedittab'] = true;
$wgGroupPermissions['user']['createclass'] = false;
$wgGroupPermissions['user']['multipageedit'] = false;
$wgGroupPermissions['sysop']['createclass'] = true;
$wgGroupPermissions['sysop']['multipageedit'] = true;
$wgGroupPermissions['sysop']['approverevisions'] = true;
$wgGroupPermissions['sysop']['moderation'] = true;
$wgGroupPermissions['sysop']['move'] = true;
$wgGroupPermissions['sysop']['move-subpages'] = true;
$wgGroupPermissions['sysop']['movefile'] = true;
$wgGroupPermissions['sysop']['editinterface'] = true;
$wgGroupPermissions['sysop']['editsitecss'] = true;
$wgGroupPermissions['sysop']['editsitejs'] = true;
$wgGroupPermissions['sysop']['skip-moderation'] = true;
$wgGroupPermissions['sysop']['skip-move-moderation'] = true;
$wgGroupPermissions['sysop']['abusefilter-modify'] = true;
$wgGroupPermissions['sysop']['abusefilter-view-private'] = true;
$wgGroupPermissions['sysop']['abusefilter-log-detail'] = true;
$wgGroupPermissions['sysop']['abusefilter-revert'] = true;
$wgGroupPermissions['sysop']['nuke'] = true;
$wgGroupPermissions['sysop']['deletedhistory'] = true;
$wgGroupPermissions['sysop']['deletedtext'] = true;
$wgGroupPermissions['sysop']['deleterevision'] = true;
$wgGroupPermissions['sysop']['oathauth-disable-for-user'] = true;
$wgGroupPermissions['sysop']['oathauth-view-log'] = true;
$wgGroupPermissions['bot']['skip-moderation'] = true;
$wgGroupPermissions['bot']['move'] = true;
$wgGroupPermissions['bot']['skip-move-moderation'] = true;
$wgGroupPermissions['bot']['upload'] = true;
$wgGroupPermissions['automoderated']['skip-moderation'] = true;
$wgGroupPermissions['automoderated']['skip-move-moderation'] = false;
$wgGroupPermissions['moderator']['moderation'] = true;
$wgGroupPermissions['moderator']['abusefilter-log'] = true;
$wgGroupPermissions['moderator']['abusefilter-log-detail'] = true;
$wgModerationEnable = true;
$wgModerationPreviewLink = true;
$wgLogRestrictions["newusers"] = 'moderation';
$wgPageFormsRenameEditTabs = true;
$wgPageFormsRenameMainEditTab = true;

$wgHooks['SpecialPageBeforeExecute'][] = static function ( $special, $subPage ) {
    if ( strtolower( $special->getName() ) !== 'specialpages' ) {
        return true;
    }
    $groups = \MediaWiki\MediaWikiServices::getInstance()
        ->getUserGroupManager()
        ->getUserEffectiveGroups( $special->getUser() );
    if ( array_intersect( [ 'sysop', 'moderator', 'bureaucrat', 'bot' ], $groups ) ) {
        return true;
    }
    $out = $special->getOutput();
    $out->setStatusCode( 403 );
    $out->showErrorPage( 'permissionserrors', 'badaccess' );
    return false;
};

# Keep uploaded media conservative until licensing workflow is mature.
$wgEnableUploads = true;
$wgGroupPermissions['user']['upload'] = false;
$wgGroupPermissions['automoderated']['upload'] = true;
$wgGroupPermissions['sysop']['upload'] = true;
$wgFileExtensions = [ 'png', 'jpg', 'jpeg', 'webp' ];
$wgStrictFileExtensions = true;

# Must be loaded last: the extension intercepts save hooks.
wfLoadExtension( 'Moderation' );
