<?php
define('ABSPATH', '/project/');
define('ARRAY_A', 'ARRAY_A');
function add_action($hook, $callback) {}
function wp_cache_delete($key, $group) {}
function clean_post_cache($id) {}
function post_type_exists($name) { return false; }
function news_weave_register_news_type() {}
function flush_rewrite_rules() {}
function check($condition, $message) {
    if (!$condition) { throw new RuntimeException($message); }
}
class MigrationDatabase {
    public $posts = 'wp_posts';
    public $options = 'wp_options';
    public $records;
    public $settings = [];
    public $saved;
    public $fail_page = false;
    public $engine = 'InnoDB';
    public $query_id;
    function __construct() {
        $this->records = [
            41 => ['ID' => 41, 'post_type' => 'nc_news', 'post_status' => 'publish',
                'post_modified_gmt' => '2026-10-07', 'post_content' => 'Original article'],
            87 => ['ID' => 87, 'post_type' => 'nc_news', 'post_status' => 'trash'],
            63 => ['ID' => 63, 'post_type' => 'page',
                'post_content' => '<!-- wp:query {"postType":"nc_news"} -->'],
        ];
    }
    function prepare($query, ...$args) {
        if (str_starts_with($query, 'SELECT post_content')) { $this->query_id = $args[0]; }
        return $query;
    }
    function get_var($query) { return $this->records[$this->query_id]['post_content']; }
    function esc_like($value) { return $value; }
    function get_row($query, $mode) { return ['Engine' => $this->engine]; }
    function query($query) {
        if ($query === 'START TRANSACTION') { $this->saved = [$this->records, $this->settings]; }
        if ($query === 'ROLLBACK') { [$this->records, $this->settings] = $this->saved; }
        return 1;
    }
    function update($table, $data, $where, $format, $where_format) {
        if ($this->fail_page && $where['ID'] === 63) { return 0; }
        $record = $this->records[$where['ID']];
        foreach ($where as $key => $value) {
            if ($record[$key] !== $value) { return 0; }
        }
        $this->records[$where['ID']] = array_merge($record, $data);
        return 1;
    }
    function replace($table, $data, $format) {
        $this->settings[$data['option_name']] = $data['option_value'];
        return 1;
    }
}
require '/project/wordpress/news-weave/includes/route-migration.php';
$wpdb = new MigrationDatabase();
$original = $wpdb->records;
$backup = ['posts' => [['ID' => 41], ['ID' => 87]], 'pages' => [$original[63]]];
news_weave_route_transaction($backup);
check($wpdb->records[41]['post_type'] === 'news_weave', 'Article not migrated');
check($wpdb->records[87]['post_type'] === 'news_weave', 'Trashed article not migrated');
check($wpdb->records[41]['post_content'] === 'Original article', 'Article content changed');
check($wpdb->records[41]['post_status'] === 'publish', 'Published status changed');
check($wpdb->records[41]['post_modified_gmt'] === '2026-10-07', 'Timestamp changed');
check(str_contains($wpdb->records[63]['post_content'], 'news_weave'), 'Listing not migrated');
check($wpdb->settings['news_weave_preserve_urls'] === '1', 'URLs not preserved');
news_weave_route_transaction($backup, true);
check($wpdb->records === $original, 'Rollback did not restore original records');
$wpdb = new MigrationDatabase();
$wpdb->fail_page = true;
try {
    news_weave_route_transaction($backup);
    throw new RuntimeException('Concurrent page change should abort');
} catch (RuntimeException $error) {
    check($wpdb->records === $original, 'Failure left partially migrated articles');
    check($wpdb->settings === [], 'Failure left new route enabled');
}
$wpdb = new MigrationDatabase();
$wpdb->engine = 'MyISAM';
try {
    news_weave_route_transaction($backup);
    throw new RuntimeException('Nontransactional database should abort');
} catch (RuntimeException $error) {
    check($wpdb->records === $original && $wpdb->saved === null, 'Unsafe engine was modified');
}
echo "PASS: article/listing migration, rollback and failure atomicity\n";
