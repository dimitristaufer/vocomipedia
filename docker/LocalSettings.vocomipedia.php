<?php
# Skeleton only. Generate a real LocalSettings.php through the MediaWiki
# installer, then merge these Vocomipedia-specific settings.

$wgSitename = "Vocomipedia";
$wgServer = "https://vocomipedia.com";
$wgEnableEmail = true;
$wgEnableUserEmail = true;
$wgEmailAuthentication = true;

# Read-only anonymous launch is the safest default.
$wgGroupPermissions['*']['edit'] = false;
$wgGroupPermissions['*']['createaccount'] = true;

# Moderation and anti-spam extensions. Install extension files before enabling.
# wfLoadExtension( 'ApprovedRevs' );
# wfLoadExtension( 'Moderation' );
# wfLoadExtension( 'AbuseFilter' );
# wfLoadExtension( 'SpamBlacklist' );
# wfLoadExtension( 'ConfirmEdit' );
# wfLoadExtension( 'DiscussionTools' );
# wfLoadExtension( 'RevisionDelete' );
# wfLoadExtension( 'TwoFactorAuthentication' );
# wfLoadExtension( 'Nuke' );

$wgGroupPermissions['sysop']['approverevisions'] = true;
$wgGroupPermissions['sysop']['moderation'] = true;
$wgGroupPermissions['sysop']['skip-moderation'] = true;
$wgGroupPermissions['sysop']['abusefilter-modify'] = true;
$wgGroupPermissions['sysop']['abusefilter-log-detail'] = true;

# Keep uploaded media conservative until licensing workflow is mature.
$wgFileExtensions = [ 'png', 'jpg', 'jpeg', 'webp' ];
$wgStrictFileExtensions = true;

