<?php

use MediaWiki\Html\Html;
use MediaWiki\MediaWikiServices;
use MediaWiki\SpecialPage\SpecialPage;
use MediaWiki\Title\Title;

class SpecialVocomipediaSearch extends SpecialPage {
    private const ITEM_NAMESPACE = 3000;
    private const DEFAULT_LIMIT = 20;
    private const MAX_RESULTS = 500;
    private const SCAN_BATCH_SIZE = 20;
    private const INDEX_CANDIDATE_LIMIT = 2500;
    private const SUPPORTED_UI_LANGUAGES = [
        'en', 'es', 'fr', 'de', 'it', 'ko', 'zh-Hans', 'yue', 'ru', 'pt', 'he', 'tr', 'vi', 'ar',
        'nl', 'uk', 'hu', 'hi', 'pl', 'el', 'nb', 'id', 'sv', 'ro', 'cs', 'da', 'fi', 'ja',
    ];

    public function __construct() {
        parent::__construct( 'VocomipediaSearch' );
    }

    public function execute( $subPage ) {
        $request = $this->getRequest();
        $out = $this->getOutput();
        $this->setHeaders();

        $term = trim( $request->getText( 'search', $subPage ?? '' ) );
        $offset = max( 0, $request->getInt( 'offset', 0 ) );
        $out->addModuleStyles( 'mediawiki.special' );
        $out->addInlineStyle( $this->styles() );
        $out->addHTML( $this->renderForm( $term ) );

        if ( $term === '' ) {
            return;
        }

        $results = $this->searchItems( $term );
        $total = count( $results );
        $slice = array_slice( $results, $offset, self::DEFAULT_LIMIT );

        $out->addHTML(
            Html::rawElement(
                'p',
                [ 'class' => 'vocomipedia-search-count' ],
                $this->getLanguage()->formatNum( $total ) . ' ranked Vocomipedia result' . ( $total === 1 ? '' : 's' )
            )
        );

        if ( !$slice ) {
            $out->addHTML(
                Html::rawElement(
                    'p',
                    [ 'class' => 'mw-search-nonefound' ],
                    'No Vocomipedia entries matched this search.'
                )
            );
        } else {
            $out->addHTML( Html::openElement( 'ol', [ 'class' => 'vocomipedia-ranked-results' ] ) );
            foreach ( $slice as $result ) {
                $out->addHTML( $this->renderResult( $result, $term ) );
            }
            $out->addHTML( Html::closeElement( 'ol' ) );
        }

        $out->addHTML( $this->renderPager( $term, $offset, $total ) );
        $fallback = SpecialPage::getTitleFor( 'Search' )->getFullURL( [
            'search' => $term,
            'fulltext' => 1,
            'vocomipediaFallback' => 1,
        ] );
        $out->addHTML(
            Html::rawElement(
                'p',
                [ 'class' => 'vocomipedia-search-fallback' ],
                Html::element( 'a', [ 'href' => $fallback ], 'Search full wiki text instead' )
            )
        );
    }

    private function searchItems( string $term ): array {
        $needle = $this->normalize( $term );
        if ( $needle === '' ) {
            return [];
        }

        $indexed = $this->searchIndexedItems( $needle );
        if ( $indexed !== null ) {
            return $indexed;
        }

        return $this->scanItemPages( $needle );
    }

    private function searchIndexedItems( string $needle ): ?array {
        $services = MediaWikiServices::getInstance();
        $dbr = $services->getConnectionProvider()->getReplicaDatabase();
        if ( !$dbr->tableExists( 'vocomipedia_search_item', __METHOD__ ) ) {
            return null;
        }
        $indexedCount = (int)$dbr->newSelectQueryBuilder()
            ->select( 'COUNT(*)' )
            ->from( 'vocomipedia_search_item' )
            ->caller( __METHOD__ )
            ->fetchField();
        if ( $indexedCount === 0 ) {
            return null;
        }

        if ( $this->booleanFulltextQuery( $needle ) !== '' ) {
            $rows = $this->indexedCandidateRows( $dbr, $needle, 'fulltext' );
            return $this->rankIndexedRows( $rows, $needle );
        }

        $rows = $this->indexedCandidateRows( $dbr, $needle, 'prefix' );
        $results = $this->rankIndexedRows( $rows, $needle );
        if ( $results ) {
            return $results;
        }

        $rows = $this->indexedCandidateRows( $dbr, $needle, 'like' );
        return $this->rankIndexedRows( $rows, $needle );
    }

    private function indexedCandidateRows( $dbr, string $needle, string $mode ) {
        $builder = $dbr->newSelectQueryBuilder()
            ->select( [ 'vsi_page_id', 'vsi_page_title', 'vsi_item_json' ] )
            ->from( 'vocomipedia_search_item' )
            ->limit( self::INDEX_CANDIDATE_LIMIT )
            ->caller( __METHOD__ );

        if ( $mode === 'fulltext' ) {
            $fulltext = $this->booleanFulltextQuery( $needle );
            $match = 'MATCH(vsi_search_text) AGAINST (' . $dbr->addQuotes( $fulltext ) . ' IN BOOLEAN MODE)';
            $builder->where( $match )->orderBy( $match, 'DESC' );
        } elseif ( $mode === 'prefix' ) {
            $exact = $dbr->addQuotes( $needle );
            $prefix = $dbr->buildLike( $needle, $dbr->anyString() );
            $builder
                ->where(
                    "(" .
                    "vsi_headword_norm = {$exact} OR vsi_reading_norm = {$exact} OR vsi_entry_norm = {$exact} OR vsi_label_norm = {$exact} OR " .
                    "vsi_headword_norm {$prefix} OR vsi_reading_norm {$prefix} OR vsi_entry_norm {$prefix} OR vsi_label_norm {$prefix}" .
                    ")"
                )
                ->orderBy( 'vsi_page_title' );
        } else {
            $builder
                ->where( 'vsi_search_text ' . $dbr->buildLike( $dbr->anyString(), $needle, $dbr->anyString() ) )
                ->orderBy( 'vsi_page_title' );
        }

        return $builder->fetchResultSet();
    }

    private function rankIndexedRows( $rows, string $needle ): array {
        $results = [];
        foreach ( $rows as $row ) {
            $item = json_decode( (string)$row->vsi_item_json, true );
            if ( !is_array( $item ) ) {
                continue;
            }
            $score = 0;
            $matches = [];
            $this->scoreItem( $item, $needle, $score, $matches );
            if ( $score <= 0 ) {
                continue;
            }
            $results[] = [
                'score' => $score,
                'title' => Title::makeTitle( self::ITEM_NAMESPACE, (string)$row->vsi_page_title ),
                'item' => $this->summarizeItem( $item ),
                'matches' => array_slice( array_values( array_unique( $matches ) ), 0, 4 ),
            ];
        }

        $this->sortResults( $results );
        return array_slice( $results, 0, self::MAX_RESULTS );
    }

    private function booleanFulltextQuery( string $needle ): string {
        if ( strlen( $needle ) < 3 && preg_match( '/^[a-z0-9]+$/', $needle ) === 1 ) {
            return '';
        }
        $terms = preg_split( '/[^\\p{L}\\p{N}]+/u', $needle ) ?: [];
        $out = [];
        foreach ( $terms as $term ) {
            $term = trim( $term );
            if ( $term === '' || mb_strlen( $term ) < 3 ) {
                continue;
            }
            $term = preg_replace( '/[+\\-@><()~*"\\\\]/u', ' ', $term );
            $term = trim( preg_replace( '/\\s+/u', ' ', $term ) );
            if ( $term !== '' ) {
                $out[] = '+' . $term . '*';
            }
        }
        return implode( ' ', $out );
    }

    private function scanItemPages( string $needle ): array {
        $services = MediaWikiServices::getInstance();
        $dbr = $services->getConnectionProvider()->getReplicaDatabase();
        $results = [];
        $lastPageId = 0;
        do {
            $rows = $dbr->newSelectQueryBuilder()
                ->select( [ 'page_id', 'page_title', 'old_text' ] )
                ->from( 'page' )
                ->join( 'revision', null, 'page_latest = rev_id' )
                ->join( 'slots', null, 'slot_revision_id = rev_id' )
                ->join( 'content', null, 'slot_content_id = content_id' )
                ->join( 'text', null, 'old_id = CAST(SUBSTRING(content_address, 4) AS UNSIGNED)' )
                ->where( [
                    'page_namespace' => self::ITEM_NAMESPACE,
                    'slot_role_id' => 1,
                ] )
                ->andWhere( $dbr->expr( 'page_id', '>', $lastPageId ) )
                ->andWhere( 'content_address LIKE ' . $dbr->addQuotes( 'tt:%' ) )
                ->orderBy( 'page_id' )
                ->limit( self::SCAN_BATCH_SIZE )
                ->caller( __METHOD__ )
                ->fetchResultSet();

            $rowCount = 0;
            foreach ( $rows as $row ) {
                $rowCount++;
                $lastPageId = (int)$row->page_id;
                $title = Title::makeTitle( self::ITEM_NAMESPACE, $row->page_title );
                $item = $this->extractItemJson( (string)$row->old_text );
                if ( !$item ) {
                    continue;
                }

                $score = 0;
                $matches = [];
                $this->scoreItem( $item, $needle, $score, $matches );
                if ( $score <= 0 ) {
                    continue;
                }

                $results[] = [
                    'score' => $score,
                    'title' => $title,
                    'item' => $this->summarizeItem( $item ),
                    'matches' => array_slice( array_values( array_unique( $matches ) ), 0, 4 ),
                ];
                unset( $item, $matches );
            }
            unset( $rows );
            if ( count( $results ) > self::MAX_RESULTS * 2 ) {
                $this->sortResults( $results );
                $results = array_slice( $results, 0, self::MAX_RESULTS );
                gc_collect_cycles();
            }
        } while ( $rowCount === self::SCAN_BATCH_SIZE );

        $this->sortResults( $results );
        return array_slice( $results, 0, self::MAX_RESULTS );
    }

    private function sortResults( array &$results ): void {
        usort( $results, static function ( array $a, array $b ): int {
            if ( $a['score'] !== $b['score'] ) {
                return $b['score'] <=> $a['score'];
            }
            $aOrder = (int)( $a['item']['order'] ?? 0 );
            $bOrder = (int)( $b['item']['order'] ?? 0 );
            if ( $aOrder !== $bOrder ) {
                return $aOrder <=> $bOrder;
            }
            return strcmp( $a['title']->getPrefixedText(), $b['title']->getPrefixedText() );
        } );
    }

    private function summarizeItem( array $item ): array {
        return [
            'headword' => $item['headword'] ?? '',
            'reading' => $item['reading'] ?? '',
            'pack_code' => $item['pack_code'] ?? '',
            'level' => $item['level'] ?? '',
            'part_of_speech' => $item['part_of_speech'] ?? [],
            'language' => $item['language'] ?? '',
            'glosses' => $item['glosses'] ?? [],
            'order' => (int)( $item['order'] ?? 0 ),
        ];
    }

    private function scoreItem( array $item, string $needle, int &$score, array &$matches ): void {
        $this->scoreText( $item['headword'] ?? '', $needle, 1200, 850, 520, $score, $matches, 'Headword' );
        $this->scoreText( $item['reading'] ?? '', $needle, 900, 640, 360, $score, $matches, 'Reading' );
        $this->scoreText( $item['entry_id'] ?? '', $needle, 700, 420, 240, $score, $matches, 'Entry id' );
        $this->scoreText( $item['label'] ?? '', $needle, 700, 420, 240, $score, $matches, 'Label' );

        foreach ( $item['glosses'] ?? [] as $lang => $gloss ) {
            $this->scoreAlternatives( (string)$gloss, $needle, 6000, 1800, 450, $score, $matches, "Gloss {$lang}" );
        }

        foreach ( $item['part_of_speech'] ?? [] as $pos ) {
            $this->scoreText( (string)$pos, $needle, 180, 120, 60, $score, $matches, 'Part of speech' );
        }

        foreach ( $item['sentences'] ?? [] as $sentenceIndex => $sentence ) {
            $number = (int)$sentenceIndex + 1;
            $this->scoreText( $sentence['target'] ?? '', $needle, 220, 140, 80, $score, $matches, "Sentence {$number}" );
            foreach ( $sentence['translations'] ?? [] as $lang => $translation ) {
                $this->scoreText( (string)$translation, $needle, 240, 140, 70, $score, $matches, "Sentence {$number} {$lang}" );
            }
            foreach ( $sentence['tokens'] ?? [] as $token ) {
                $this->scoreText( $token['surface'] ?? '', $needle, 420, 260, 140, $score, $matches, 'Token' );
                $this->scoreText( $token['lemma'] ?? '', $needle, 380, 240, 130, $score, $matches, 'Lemma' );
                $this->scoreAlternatives( $token['surface_en'] ?? '', $needle, 900, 360, 120, $score, $matches, 'Token meaning' );
                $this->scoreText( $token['explanation'] ?? '', $needle, 90, 50, 25, $score, $matches, 'Token note' );
            }
        }
    }

    private function scoreAlternatives(
        string $value,
        string $needle,
        int $exact,
        int $prefix,
        int $contains,
        int &$score,
        array &$matches,
        string $label
    ): void {
        foreach ( $this->alternatives( $value ) as $alternative ) {
            $this->scoreText( $alternative, $needle, $exact, $prefix, $contains, $score, $matches, $label );
        }
        $this->scoreText( $value, $needle, (int)( $exact * 0.25 ), (int)( $prefix * 0.5 ), $contains, $score, $matches, $label );
    }

    private function scoreText(
        string $value,
        string $needle,
        int $exact,
        int $prefix,
        int $contains,
        int &$score,
        array &$matches,
        string $label
    ): void {
        $value = trim( $value );
        if ( $value === '' ) {
            return;
        }
        $haystack = $this->normalize( $value );
        if ( $haystack === '' ) {
            return;
        }
        if ( $haystack === $needle ) {
            $score += $exact + $this->shortValueBonus( $haystack );
            $matches[] = "{$label}: {$value}";
        } elseif ( str_starts_with( $haystack, $needle ) && $this->isBoundaryAfterNeedle( $haystack, $needle ) ) {
            $score += $prefix + $this->shortValueBonus( $haystack );
            $matches[] = "{$label}: {$value}";
        } elseif ( $this->containsNeedle( $haystack, $needle ) ) {
            $score += $contains;
            $matches[] = "{$label}: {$value}";
        }
    }

    private function containsNeedle( string $haystack, string $needle ): bool {
        if ( !$this->isShortAsciiNeedle( $needle ) ) {
            return str_contains( $haystack, $needle );
        }
        return preg_match( '/(^|[^\\p{L}\\p{N}])' . preg_quote( $needle, '/' ) . '([^\\p{L}\\p{N}]|$)/u', $haystack ) === 1;
    }

    private function isBoundaryAfterNeedle( string $haystack, string $needle ): bool {
        if ( !$this->isShortAsciiNeedle( $needle ) ) {
            return true;
        }
        $next = mb_substr( $haystack, mb_strlen( $needle ), 1 );
        return $next === '' || preg_match( '/[^\\p{L}\\p{N}]/u', $next ) === 1;
    }

    private function isShortAsciiNeedle( string $needle ): bool {
        return strlen( $needle ) <= 3 && preg_match( '/^[a-z0-9]+$/', $needle ) === 1;
    }

    private function shortValueBonus( string $value ): int {
        $length = max( 1, mb_strlen( $value ) );
        return max( 0, 90 - min( 80, $length * 4 ) );
    }

    private function alternatives( string $value ): array {
        $parts = preg_split( '/\\s*(?:\\/|,|;|·|\\||、|，|；)\\s*/u', $value ) ?: [];
        $out = [];
        foreach ( $parts as $part ) {
            $part = trim( preg_replace( '/^[\\[\\(\\{]+|[\\]\\)\\}]+$/u', '', trim( $part ) ) );
            if ( $part !== '' ) {
                $out[] = $part;
                $plain = trim( preg_replace( '/\\s*[\\(\\[].*$/u', '', $part ) );
                if ( $plain !== '' ) {
                    $out[] = $plain;
                }
            }
        }
        return array_values( array_unique( $out ) );
    }

    private function normalize( string $value ): string {
        $value = trim( mb_strtolower( $value ) );
        $value = preg_replace( '/\\s+/u', ' ', $value );
        $value = preg_replace( '/^[\\p{P}\\p{S}]+|[\\p{P}\\p{S}]+$/u', '', $value );
        return trim( $value );
    }

    private function extractItemJson( string $text ): ?array {
        if ( !preg_match( '/VOCOMIPEDIA_ITEM_JSON_START\\s*(.*?)\\s*VOCOMIPEDIA_ITEM_JSON_END/s', $text, $match ) ) {
            return null;
        }
        $json = trim( $match[1] );
        if ( str_ends_with( $json, '--' ) ) {
            $json = trim( substr( $json, 0, -2 ) );
        }
        $data = json_decode( $json, true );
        return is_array( $data ) ? $data : null;
    }

    private function renderForm( string $term ): string {
        return Html::rawElement(
            'form',
            [ 'method' => 'get', 'action' => $this->getPageTitle()->getLocalURL(), 'class' => 'vocomipedia-search-form' ],
            Html::element( 'input', [
                'type' => 'search',
                'name' => 'search',
                'value' => $term,
                'placeholder' => 'Search headwords, readings, translations, and examples',
            ] ) .
            Html::element( 'button', [ 'type' => 'submit' ], 'Search' )
        );
    }

    private function renderResult( array $result, string $term ): string {
        $item = $result['item'];
        $title = $result['title'];
        $headword = (string)( $item['headword'] ?? $title->getText() );
        $reading = (string)( $item['reading'] ?? '' );
        $label = $headword . ( $reading !== '' && $reading !== $headword ? " [{$reading}]" : '' );
        $meta = array_filter( [
            $item['pack_code'] ?? '',
            $item['level'] ?? '',
            implode( ', ', $item['part_of_speech'] ?? [] ),
            $item['language'] ?? '',
        ] );
        $glosses = $this->primaryGlosses( $item['glosses'] ?? [], $this->preferredUiLanguage() );
        $matches = $result['matches'] ?: [ 'Matched item content' ];

        return Html::rawElement(
            'li',
            [ 'class' => 'vocomipedia-ranked-result' ],
            Html::rawElement(
                'div',
                [ 'class' => 'vocomipedia-ranked-title' ],
                Html::element( 'a', [ 'href' => $title->getLocalURL() ], $label )
            ) .
            Html::rawElement(
                'div',
                [ 'class' => 'vocomipedia-ranked-meta' ],
                htmlspecialchars( implode( ' · ', $meta ) ) . ' · score ' . (int)$result['score']
            ) .
            Html::element( 'div', [ 'class' => 'vocomipedia-ranked-glosses' ], $glosses ) .
            Html::rawElement(
                'ul',
                [ 'class' => 'vocomipedia-ranked-matches' ],
                implode( '', array_map(
                    static fn ( string $match ): string => Html::element( 'li', [], $match ),
                    $matches
                ) )
            )
        );
    }

    private function primaryGlosses( array $glosses, string $uiLanguage ): string {
        $preferred = array_values( array_unique( array_filter( [
            $uiLanguage,
            'en',
            'de',
            'es',
            'fr',
            'it',
            'ja',
            'ko',
            'zh-Hans',
        ] ) ) );
        $parts = [];
        foreach ( $preferred as $lang ) {
            if ( isset( $glosses[$lang] ) && trim( (string)$glosses[$lang] ) !== '' ) {
                $parts[] = "{$lang}: " . trim( (string)$glosses[$lang] );
            }
            if ( count( $parts ) >= 4 ) {
                break;
            }
        }
        if ( !$parts ) {
            foreach ( $glosses as $lang => $gloss ) {
                if ( trim( (string)$gloss ) !== '' ) {
                    $parts[] = "{$lang}: " . trim( (string)$gloss );
                }
                if ( count( $parts ) >= 4 ) {
                    break;
                }
            }
        }
        return implode( ' · ', $parts );
    }

    private function preferredUiLanguage(): string {
        $candidates = [ $this->getLanguage()->getCode() ];
        $acceptLanguage = $this->getRequest()->getHeader( 'Accept-Language' );
        if ( $acceptLanguage !== false && trim( (string)$acceptLanguage ) !== '' ) {
            foreach ( explode( ',', (string)$acceptLanguage ) as $part ) {
                $candidates[] = preg_replace( '/;.*$/', '', trim( $part ) );
            }
        }
        foreach ( $candidates as $candidate ) {
            $normalized = $this->normalizeUiLanguage( (string)$candidate );
            if ( $normalized !== '' ) {
                return $normalized;
            }
        }
        return 'en';
    }

    private function normalizeUiLanguage( string $code ): string {
        $code = str_replace( '_', '-', trim( $code ) );
        if ( $code === '' ) {
            return '';
        }
        $lower = strtolower( $code );
        $aliases = [
            'zh' => 'zh-Hans',
            'zh-cn' => 'zh-Hans',
            'zh-sg' => 'zh-Hans',
            'zh-hans' => 'zh-Hans',
            'no' => 'nb',
            'nb-no' => 'nb',
            'pt-br' => 'pt',
            'pt-pt' => 'pt',
        ];
        if ( isset( $aliases[$lower] ) ) {
            return $aliases[$lower];
        }
        foreach ( self::SUPPORTED_UI_LANGUAGES as $supported ) {
            if ( strtolower( $supported ) === $lower ) {
                return $supported;
            }
        }
        $base = explode( '-', $lower )[0] ?? '';
        foreach ( self::SUPPORTED_UI_LANGUAGES as $supported ) {
            if ( strtolower( $supported ) === $base ) {
                return $supported;
            }
        }
        return '';
    }

    private function renderPager( string $term, int $offset, int $total ): string {
        if ( $total <= self::DEFAULT_LIMIT ) {
            return '';
        }
        $links = [];
        if ( $offset > 0 ) {
            $links[] = Html::element( 'a', [
                'href' => $this->getPageTitle()->getFullURL( [
                    'search' => $term,
                    'offset' => max( 0, $offset - self::DEFAULT_LIMIT ),
                ] ),
            ], 'Previous' );
        }
        if ( $offset + self::DEFAULT_LIMIT < $total ) {
            $links[] = Html::element( 'a', [
                'href' => $this->getPageTitle()->getFullURL( [
                    'search' => $term,
                    'offset' => $offset + self::DEFAULT_LIMIT,
                ] ),
            ], 'Next' );
        }
        return Html::rawElement( 'p', [ 'class' => 'vocomipedia-search-pager' ], implode( ' ', $links ) );
    }

    private function styles(): string {
        return <<<CSS
.vocomipedia-search-form {
  display: flex;
  gap: .5rem;
  margin: 1rem 0 1.25rem;
  max-width: 48rem;
}
.vocomipedia-search-form input[type="search"] {
  flex: 1;
  min-width: 12rem;
  padding: .45rem .55rem;
}
.vocomipedia-search-form button {
  padding: .45rem .8rem;
}
.vocomipedia-ranked-results {
  margin-left: 0;
  padding-left: 0;
  list-style: none;
}
.vocomipedia-ranked-result {
  border-top: 1px solid #c8ccd1;
  padding: .75rem 0 .85rem;
}
.vocomipedia-ranked-title {
  font-size: 1.18rem;
  font-weight: 700;
}
.vocomipedia-ranked-meta,
.vocomipedia-ranked-glosses,
.vocomipedia-ranked-matches {
  color: #54595d;
  font-size: .92rem;
  margin-top: .2rem;
}
.vocomipedia-ranked-matches {
  margin-bottom: 0;
}
.skin-theme-clientpref-night .vocomipedia-ranked-result {
  border-color: #54595d;
}
.skin-theme-clientpref-night .vocomipedia-ranked-meta,
.skin-theme-clientpref-night .vocomipedia-ranked-glosses,
.skin-theme-clientpref-night .vocomipedia-ranked-matches {
  color: #c8ccd1;
}
CSS;
    }
}
