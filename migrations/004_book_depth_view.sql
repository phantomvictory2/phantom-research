-- =============================================================================
-- 004_book_depth_view.sql — read-only research view over order-book depth
-- =============================================================================
-- Phase 2 added public.book_depth (written by the collector): the price AND
-- size at each level of the Polymarket outcome-token order book, captured every
-- tick. This is the size-at-ask data that execution realism needs and that the
-- price-only snapshots lacked (the H003 executability blocker).
--
-- This migration exposes that raw table to the research engine as a clean,
-- read-only projection. It NEVER writes to public.book_depth — the collector
-- owns that table. The view is created only if the table already exists, so a
-- research deploy that lands before the collector's first run cannot fail here.
-- =============================================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'book_depth'
    ) THEN
        EXECUTE $v$
            CREATE OR REPLACE VIEW research.clean_book_depth AS
            SELECT bd.slug,
                   bd.duration,
                   bd.elapsed_s,
                   bd.captured_at,
                   bd.up_best_bid,
                   bd.up_best_bid_size,
                   bd.up_best_ask,
                   bd.up_best_ask_size,
                   bd.up_bids,
                   bd.up_asks,
                   bd.down_best_bid,
                   bd.down_best_bid_size,
                   bd.down_best_ask,
                   bd.down_best_ask_size,
                   bd.down_bids,
                   bd.down_asks,
                   bd.up_spread,
                   bd.up_imbalance,
                   m.open_time,
                   m.close_time,
                   m.window_ts
            FROM book_depth bd
            JOIN markets m ON bd.slug = m.slug
            WHERE bd.elapsed_s BETWEEN 0 AND 300
        $v$;
        RAISE NOTICE 'research.clean_book_depth created/updated';
    ELSE
        RAISE NOTICE 'public.book_depth not present yet; skipping clean_book_depth view';
    END IF;
END $$;
