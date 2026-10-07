<?php
/**
 * Plugin Name: News Collection Articles
 * Description: News Collection System用のREST API対応ニュース投稿タイプ。
 * Version: 1.0.0
 */

if (!defined('ABSPATH')) {
    exit;
}

function ncs_register_news_type() {
    register_post_type('nc_news', [
        'labels' => [
            'name' => '収集ニュース',
            'singular_name' => '収集ニュース',
        ],
        'public' => true,
        'show_in_rest' => true,
        'rest_base' => 'nc-news',
        'has_archive' => false,
        'rewrite' => ['slug' => 'collected-news'],
        'menu_icon' => 'dashicons-media-document',
        'supports' => ['title', 'editor', 'excerpt', 'thumbnail', 'author', 'revisions'],
        'taxonomies' => ['category', 'post_tag'],
    ]);
}
add_action('init', 'ncs_register_news_type');

function ncs_activate_news_type() {
    ncs_register_news_type();
    flush_rewrite_rules();
}
register_activation_hook(__FILE__, 'ncs_activate_news_type');
