<?php
/**
 * Plugin Name: News Weave
 * Description: 「ニュースを編む」のREST API対応ニュース投稿タイプ。
 * Version: 1.2.0
 * Text Domain: news-weave
 */

if (!defined('ABSPATH')) {
    exit;
}

function news_weave_register_news_type() {
    // Existing sites opt in to the original storage type, REST route and URLs.
    // Keep these identities together: the sender's history also depends on them.
    $legacy = defined('NEWS_WEAVE_LEGACY_ROUTES') && NEWS_WEAVE_LEGACY_ROUTES
        && !get_option('news_weave_routes_migrated', false);
    $preserve_urls = $legacy || get_option('news_weave_preserve_urls', false);
    register_post_type($legacy ? 'nc_news' : 'news_weave', [
        'labels' => [
            'name' => 'ニュースを編む',
            'singular_name' => 'ニュースを編む',
        ],
        'public' => true,
        'show_in_rest' => true,
        'rest_base' => $legacy ? 'nc-news' : 'news-weave',
        'has_archive' => false,
        'rewrite' => ['slug' => $preserve_urls ? 'collected-news' : 'news-weave'],
        'menu_icon' => 'dashicons-media-document',
        'supports' => ['title', 'editor', 'excerpt', 'thumbnail', 'author', 'revisions'],
        'taxonomies' => ['category', 'post_tag'],
    ]);
}
add_action('init', 'news_weave_register_news_type');

function news_weave_activate_news_type() {
    news_weave_register_news_type();
    flush_rewrite_rules();
}
register_activation_hook(__FILE__, 'news_weave_activate_news_type');

require_once __DIR__ . '/includes/route-migration.php';
