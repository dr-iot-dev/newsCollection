<?php
// Administrator-only migration: retain article IDs, content, status and URLs.
if (!defined('ABSPATH')) {
    exit;
}

function news_weave_route_plan() {
    global $wpdb;
    $posts = $wpdb->get_results($wpdb->prepare(
        "SELECT ID, post_status, post_name, post_modified_gmt FROM {$wpdb->posts}
         WHERE post_type = %s ORDER BY ID", 'nc_news'
    ), ARRAY_A);
    $pages = $wpdb->get_results($wpdb->prepare(
        "SELECT ID, post_content FROM {$wpdb->posts}
         WHERE post_type IN ('page','wp_template','wp_template_part','wp_block')
         AND post_content LIKE %s ORDER BY ID",
        '%' . $wpdb->esc_like('"postType":"nc_news"') . '%'
    ), ARRAY_A);
    return ['posts' => $posts, 'pages' => $pages];
}

function news_weave_route_transaction($backup, $rollback = false) {
    global $wpdb;
    foreach ([$wpdb->posts, $wpdb->options] as $table) {
        $info = $wpdb->get_row($wpdb->prepare('SHOW TABLE STATUS LIKE %s', $wpdb->esc_like($table)), ARRAY_A);
        if (!$info || strtolower($info['Engine']) !== 'innodb') {
            throw new RuntimeException('移行にはInnoDBのトランザクションが必要です。');
        }
    }
    if ($wpdb->query('START TRANSACTION') === false) {
        throw new RuntimeException('移行トランザクションを開始できませんでした。');
    }
    try {
        foreach ($backup['posts'] as $post) {
            $updated = $wpdb->update($wpdb->posts,
                ['post_type' => $rollback ? 'nc_news' : 'news_weave'],
                ['ID' => (int)$post['ID'], 'post_type' => $rollback ? 'news_weave' : 'nc_news'],
                ['%s'], ['%d', '%s']
            );
            if ($updated !== 1) {
                throw new RuntimeException('記事の状態が変わったため移行を中止しました。');
            }
        }
        foreach ($backup['pages'] as $page) {
            $new = str_replace('"postType":"nc_news"', '"postType":"news_weave"', $page['post_content']);
            $current = $wpdb->get_var($wpdb->prepare(
                "SELECT post_content FROM {$wpdb->posts} WHERE ID = %d FOR UPDATE", (int)$page['ID']
            ));
            if ($current !== ($rollback ? $new : $page['post_content'])) {
                throw new RuntimeException('一覧ページが変更されたため移行を中止しました。');
            }
            $updated = $wpdb->update($wpdb->posts,
                ['post_content' => $rollback ? $page['post_content'] : $new],
                ['ID' => (int)$page['ID'], 'post_content' => $rollback ? $new : $page['post_content']],
                ['%s'], ['%d', '%s']
            );
            if ($updated !== 1) {
                throw new RuntimeException('一覧ページが変更されたため移行を中止しました。');
            }
        }
        foreach (['news_weave_routes_migrated', 'news_weave_preserve_urls'] as $option) {
            if ($wpdb->replace($wpdb->options, [
                'option_name' => $option, 'option_value' => $rollback ? '0' : '1', 'autoload' => 'no',
            ], ['%s', '%s', '%s']) === false) {
                throw new RuntimeException('移行設定を保存できませんでした。');
            }
        }
        if ($wpdb->query('COMMIT') === false) {
            throw new RuntimeException('移行を確定できませんでした。');
        }
    } catch (Throwable $error) {
        $wpdb->query('ROLLBACK');
        throw $error;
    }
    wp_cache_delete('alloptions', 'options');
    wp_cache_delete('notoptions', 'options');
    foreach (['news_weave_routes_migrated', 'news_weave_preserve_urls'] as $option) {
        wp_cache_delete($option, 'options');
    }
    foreach (array_merge($backup['posts'], $backup['pages']) as $post) {
        clean_post_cache((int)$post['ID']);
    }
    if (post_type_exists('nc_news')) {
        unregister_post_type('nc_news');
    }
    if (post_type_exists('news_weave')) {
        unregister_post_type('news_weave');
    }
    news_weave_register_news_type();
    flush_rewrite_rules();
}

function news_weave_route_submit() {
    if (!current_user_can('manage_options')) {
        wp_die('管理者権限が必要です。');
    }
    check_admin_referer('news_weave_route_migration');
    $rollback = isset($_POST['migration_operation']) && $_POST['migration_operation'] === 'rollback';
    try {
        if ($rollback) {
            $backup = get_option('news_weave_route_migration_backup', false);
            if (!$backup || !get_option('news_weave_routes_migrated', false)) {
                throw new RuntimeException('復旧対象の移行記録がありません。');
            }
            news_weave_route_transaction($backup, true);
        } else {
            if (get_option('news_weave_routes_migrated', false)) {
                throw new RuntimeException('移行は既に完了しています。');
            }
            global $wpdb;
            if ((int)$wpdb->get_var($wpdb->prepare(
                "SELECT COUNT(*) FROM {$wpdb->posts} WHERE post_type = %s", 'news_weave'
            )) !== 0) {
                throw new RuntimeException('移行先に記事が存在するため中止しました。');
            }
            $backup = news_weave_route_plan();
            if (!$backup['posts']) {
                throw new RuntimeException('旧投稿タイプの記事がありません。');
            }
            $backup['created_at'] = gmdate('c');
            if (!update_option('news_weave_route_migration_backup', $backup, false)
                && get_option('news_weave_route_migration_backup') !== $backup) {
                throw new RuntimeException('移行前の記録を保存できませんでした。');
            }
            news_weave_route_transaction($backup);
        }
    } catch (Throwable $error) {
        wp_die(esc_html($error->getMessage()));
    }
    wp_safe_redirect(admin_url('tools.php?page=news-weave-routes'));
    exit;
}
add_action('admin_post_news_weave_migrate_routes', 'news_weave_route_submit');

function news_weave_route_page() {
    if (!current_user_can('manage_options')) {
        return;
    }
    $migrated = get_option('news_weave_routes_migrated', false);
    $plan = $migrated ? get_option('news_weave_route_migration_backup', []) : news_weave_route_plan();
    echo '<div class="wrap"><h1>News Weaveの投稿タイプ移行</h1>';
    echo '<p>投稿タイプ <code>nc_news → news_weave</code> / REST <code>nc-news → news-weave</code></p>';
    echo '<p>記事ID、本文、投稿者、公開状態、画像、記事URLを維持します。一覧ページのクエリーも更新します。</p>';
    echo '<p><strong>' . ($migrated ? '移行完了' : '移行前') . '</strong></p>';
    echo '<p>記事ID（ゴミ箱を含む）: ' . esc_html(implode(', ', array_column($plan['posts'] ?? [], 'ID'))) . '</p>';
    echo '<p>一覧・テンプレートID: ' . esc_html(implode(', ', array_column($plan['pages'] ?? [], 'ID'))) . '</p>';
    echo '<p>アプリ側の送信履歴と設定も同じ移行作業で切り替えてください。</p>';
    echo '<form method="post" action="' . esc_url(admin_url('admin-post.php')) . '">';
    echo '<input type="hidden" name="action" value="news_weave_migrate_routes">';
    echo '<input type="hidden" name="migration_operation" value="' . ($migrated ? 'rollback' : 'migrate') . '">';
    wp_nonce_field('news_weave_route_migration');
    submit_button($migrated ? '旧投稿タイプへ戻す' : 'news_weave / news-weaveへ移行する');
    echo '</form></div>';
}

function news_weave_route_menu() {
    add_management_page('News Weaveの投稿タイプ移行', 'News Weaveの移行', 'manage_options',
        'news-weave-routes', 'news_weave_route_page');
}
add_action('admin_menu', 'news_weave_route_menu');
