CREATE TABLE articles (
	id VARCHAR(36) NOT NULL,
	url VARCHAR NOT NULL,
	company_id VARCHAR NOT NULL,
	company_name VARCHAR NOT NULL,
	release_id INTEGER NOT NULL,
	published_at VARCHAR NOT NULL,
	title VARCHAR NOT NULL,
	body VARCHAR NOT NULL,
	domains JSON NOT NULL,
	release_type VARCHAR NOT NULL,
	raw_html VARCHAR NOT NULL,
	snapshot_hash VARCHAR NOT NULL,
	fetched_at VARCHAR NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (url, snapshot_hash),
	CHECK (release_type = '01')
);

CREATE INDEX ix_articles_company_id ON articles (company_id);

CREATE TABLE runs (
	id VARCHAR(36) NOT NULL,
	created_at VARCHAR NOT NULL,
	step VARCHAR NOT NULL,
	error VARCHAR,
	settings JSON NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE run_articles (
	run_id VARCHAR(36) NOT NULL,
	article_id VARCHAR(36) NOT NULL,
	embedding JSON,
	cluster_id INTEGER,
	PRIMARY KEY (run_id, article_id),
	FOREIGN KEY(run_id) REFERENCES runs (id),
	FOREIGN KEY(article_id) REFERENCES articles (id)
);

CREATE TABLE comparisons (
	id VARCHAR(36) NOT NULL,
	run_id VARCHAR(36) NOT NULL,
	cluster_id INTEGER NOT NULL,
	source1 VARCHAR,
	source2 VARCHAR,
	source3 VARCHAR,
	reserve1 VARCHAR,
	reserve2 VARCHAR,
	reserve3 VARCHAR,
	candidate_article_ids JSON NOT NULL,
	selection_result JSON NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (run_id, cluster_id),
	CHECK (cluster_id >= 0),
	CHECK ((source1 IS NULL AND source2 IS NULL AND source3 IS NULL) OR (source1 IS NOT NULL AND source2 IS NOT NULL AND source3 IS NOT NULL AND source1 <> source2 AND source1 <> source3 AND source2 <> source3)),
	CHECK ((reserve1 IS NULL AND reserve2 IS NULL AND reserve3 IS NULL) OR (reserve1 IS NOT NULL AND reserve2 IS NOT NULL AND reserve3 IS NOT NULL AND reserve1 <> reserve2 AND reserve1 <> reserve3 AND reserve2 <> reserve3)),
	CHECK (reserve1 IS NULL OR source1 IS NOT NULL),
	FOREIGN KEY(run_id, source1) REFERENCES run_articles (run_id, article_id),
	FOREIGN KEY(run_id, source2) REFERENCES run_articles (run_id, article_id),
	FOREIGN KEY(run_id, source3) REFERENCES run_articles (run_id, article_id),
	FOREIGN KEY(run_id, reserve1) REFERENCES run_articles (run_id, article_id),
	FOREIGN KEY(run_id, reserve2) REFERENCES run_articles (run_id, article_id),
	FOREIGN KEY(run_id, reserve3) REFERENCES run_articles (run_id, article_id),
	FOREIGN KEY(run_id) REFERENCES runs (id)
);

CREATE TABLE drafts (
	id VARCHAR(36) NOT NULL,
	comparison_id VARCHAR(36) NOT NULL,
	set_role VARCHAR NOT NULL,
	generation_status VARCHAR,
	generation_reason VARCHAR,
	revision INTEGER NOT NULL,
	markdown VARCHAR,
	created_at VARCHAR NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (comparison_id, set_role, revision),
	CHECK (set_role IN ('PRIMARY', 'RESERVE')),
	CHECK (generation_status IN ('APPROPRIATE', 'INAPPROPRIATE')),
	CHECK (revision IN (0, 1)),
	CHECK (revision = 1 OR markdown IS NOT NULL),
	CHECK (revision = 1 OR generation_status IS NOT NULL),
	FOREIGN KEY(comparison_id) REFERENCES comparisons (id)
);

CREATE TABLE verifications (
	draft_id VARCHAR(36) NOT NULL,
	status VARCHAR NOT NULL,
	score INTEGER,
	reason VARCHAR NOT NULL,
	created_at VARCHAR NOT NULL,
	PRIMARY KEY (draft_id),
	CHECK (status IN ('eligible', 'ineligible', 'needs_confirmation')),
	CHECK (score BETWEEN 0 AND 100),
	FOREIGN KEY(draft_id) REFERENCES drafts (id)
);
