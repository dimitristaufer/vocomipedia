<?php

use MediaWiki\SpecialPage\SpecialPage;

class VocomipediaSearchHooks {
    public static function onSpecialPageBeforeExecute( SpecialPage $special, $subPage ) {
        if ( strtolower( $special->getName() ) !== 'search' ) {
            return true;
        }

        $request = $special->getRequest();
        $term = trim( $request->getText( 'search', '' ) );
        if ( $term === '' || $request->getBool( 'vocomipediaFallback' ) ) {
            return true;
        }

        $params = [ 'search' => $term ];
        $offset = $request->getIntOrNull( 'offset' );
        if ( $offset !== null && $offset > 0 ) {
            $params['offset'] = $offset;
        }

        $special->getOutput()->redirect(
            SpecialPage::getTitleFor( 'VocomipediaSearch' )->getFullURL( $params )
        );
        return false;
    }
}
