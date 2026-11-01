#!/usr/bin/env python3
"""
incoming_processor.py  v3.2

VERSION HISTORY (bump on every change so you always know what's current):
  v1.0  Initial multi-stage matching pipeline (Stage 1-3), portable config.
  v1.1  Portable edition: setup docstring, dependency notes, config block.
  v2.0  BREAKING: consolidated lowercase folder layout (see migrate_
        folder_structure.py). Stage 0 exact-name match added before
        Stage 1. Numbered-series guard in fuzzy validation (vol6 no
        longer matches vol2). Group-tag token-overlap bugfix. Dupe
        detection now authoritative on the scenereleases/ folder
        instead of the DB (DB is history-only). HTTP retry+backoff
        and per-run search cache for srrDB. Single-pass folder scan
        and CRC cache between rename and check. Grouped, reasoned
        results log at the end of every run. SRR_PY moved into the
        config block.
  v2.1  BUGFIX: case-only file renames could get permanently stuck as
        "*__rename_tmp__" / "*__crc_tmp__" if the second half of the
        two-step rename failed (e.g. a CIFS/NFS mount going stale
        mid-run) — no rollback existed, so the media file effectively
        vanished from the release and the SFV check reported it as
        MISSING forever. Both rename paths now roll back to the
        original filename on failure and log clearly instead of
        raising. Any tmp files already stuck from a previous run are
        now auto-healed at the start of processing.
  v2.2  BUGFIX: "RENAME SUMMARY" always showed 0 renamed on
        case-insensitive mounts (CIFS/SMB) even when files were
        actually being corrected. The case-only-fix path (used when
        a file already exists under the right name but wrong letter
        case) never incremented the renamed counter — only the
        CRC-lookup rename path did. Both paths now count correctly,
        so the summary reflects what actually happened.
  v2.3  Clearer wording for the dupe file-name comparison. "14 only
        in dupe, 14 only in original" was ambiguous — it looked the
        same whether one file differed or all of them did. Now
        distinguishes three cases explicitly: identical names,
        completely different naming scheme (zero filenames in
        common — almost always the same release under a different
        naming convention, not a broken duplicate), or a partial
        mismatch with the count of names actually shared.
  v2.4  Stage 0 (exact folder name match) shared its counter with
        Stage 1 (stem search) in the summary, so a Stage 0 hit
        silently showed up as "Stage 1 stem matches" with no way to
        tell them apart without reading the detailed log. Stage 0
        now has its own "exact_match" counter and its own summary
        line.
  v2.5  Stage 1 exact stem match was silently discarding a perfectly
        good single srrDB result when the local NFO filename was
        missing a country/language tag present in the canonical name
        (e.g. local "...-VLS-1998-KrbZ" vs the real srrDB
        "...-VLS-DE-1998-KrbZ" — strict token-set equality rejected
        it over one missing "DE"). Now tolerates exactly this case:
        a single srrDB result whose only token difference is a known
        country/language code is accepted, and logged clearly so
        it's visible when the tolerance kicked in.
  v2.6  BUGFIX: Stage 3 (ID3/NFO fallback) validated every srrDB
        candidate against the raw ON-DISK FOLDER NAME instead of the
        album text from ID3/NFO tags. This is harmless for normally-
        named folders, but releases arriving via generic downloaders
        (Usenet nzb clients, etc.) often sit in meaninglessly-named
        folders like "nzb_2ae9746117fc51b0481984c50e74e5bd" — token
        overlap against that garbage was always 0%, and the series-
        number guard always saw "no ordinal" and rejected any
        candidate with one (e.g. "(12-Inch)", "Weltretten_4"),
        so Stage 3 rejected obviously correct matches wholesale.
        Now validates against the album tag, which actually
        describes the release; year/group continue to be validated
        separately via ID3/NFO as before, unaffected by this fix.
  v2.7  Diagnosed 14 real nzb_* releases (via diagnose_nomatch.py)
        that still failed Stage 3 after v2.6 and found five further,
        independent bugs, all fixed:
          - extract_from_id3 only ever read .mp3 files, so FLAC-only
            releases (e.g. Dilated_Peoples-Directors_Of_Photography)
            got no album/year/group at all and Stage 3 skipped them
            outright. Now also reads FLAC Vorbis comments.
          - The id3-filename group guess (trailing "-XXXX.mp3")
            trusted the FIRST track only, so a release with no real
            group suffix could grab a word from that one track's
            title and mistake it for the group (Nas-The_Lost_Tapes
            "01-nas-freestyle.mp3" → wrongly read "FREESTYLE" as the
            group). Now only trusted if identical across every track.
          - folder_to_tokens drops tokens of length <= 2, so a
            heavily-abbreviated album like "E.L.E." (Busta Rhymes)
            tokenized to nothing, auto-rejecting an otherwise perfect
            match. Falls back to an unfiltered token set when empty.
          - Some ID3 album tags are pure format noise, not a real
            title (Souls Of Mischief's TALB is literally 12"). These
            are now detected and replaced with the NFO/SFV filename
            stem instead.
          - The album tag alone doesn't include the artist name, so
            an all-digit or single-word title (Vorzeichen's "1 2 3")
            left nothing at all to compare against a candidate, which
            always includes the artist. Compare-text is now artist +
            album together.
        Verified against all 13 releases with usable metadata from
        the diagnostic dump (the 14th, an all-digit ID3 tag
        truncation edge case, incidentally also fixed by tightening
        the roman-numeral guard to require 2+ letters, so a stray
        truncated "I" no longer gets mistaken for a series numeral).
  v2.8  BUGFIX: group comparison rejected "FTD" vs the real "FTD_INT"
        outright — "_INT" is a common Scene suffix marking an
        internal release by the SAME group, but local files often
        don't carry it in their filenames while srrDB's canonical
        name does (confirmed via a real srrDB search returning a
        single, obviously-correct result for
        Slum_Village-Fan-Tas-Tic_Vol._1-2006-FTD_INT). Group
        comparison now tolerates exactly a +/- "_INT" difference,
        nothing looser. One historical regression test that used
        CMS vs CMS_INT as an arbitrary "these must differ" example
        was updated to reflect this intentional change; a genuine
        mismatch (a completely different group) is still rejected
        as before.
  v2.9  BUGFIX: the v2.7 fix taught VALIDATION to compare candidates
        against artist+album (not album alone), but the actual
        srrDB SEARCH QUERY sent by Stage 3 still only ever contained
        album/year/group — never the artist. For a short album title
        like "E.L.E." (Busta Rhymes) the query became just "E.L.E.
        1998 RNS" with no artist name at all, which returned nothing
        useful from srrDB's search API even though the release is
        found instantly once the artist name is part of the query
        (confirmed by hand: searching "E.L.E." alone via the API
        failed, adding "busta_rhymes" to the query succeeded). The
        search query now includes the artist name too, matching what
        was already fixed for validation two versions ago.
  v2.10 BUGFIX: the v2.8 "_INT" group tolerance was bidirectional,
        accepting "GROUP" vs "GROUP_INT" in EITHER direction. That's
        wrong: when srrDB's canonical name has "_INT" and the local
        name is simply missing it (the original Slum_Village case),
        srrDB is the only record of that release and trusting it is
        safe. But when the LOCAL folder explicitly declares itself
        "..._INT" and the matched candidate does NOT have "_INT",
        accepting it silently relabels a release that was never
        actually on srrDB under a different release's identity —
        confirmed as a real false positive via manual review
        (Lost_Children_Of_Babylon-...-CMS_INT was wrongly matched to
        and renamed as a same-named but non-INT "CMS" release that
        is NOT the same catalog entry). The tolerance is now strictly
        one-directional: only local-missing-INT vs candidate-has-INT
        is accepted, never the reverse.
  v2.11 BUGFIX (major): the final audio CRC check used
        find_sfv(folder)[0] — whichever .sfv happened to sort first
        on disk — completely disconnected from whichever .sfv/
        metadata actually matched the canonical release in Stage 0-3.
        If a folder contained a second, unrelated .sfv (e.g. stray
        metadata from a different release that got bundled in by
        mistake, or a self-generated .sfv describing only the local
        files themselves), the audio check could run against that
        second file instead. A self-generated .sfv was never checked
        against srrDB at all, so this let a folder "pass" purely by
        matching its own files to itself — no real verification
        happened, while the release got confidently renamed and
        moved into scenereleases under a completely unrelated
        release's identity. Confirmed via real cases from a live run:
        Large_Professor-The_LP got moved into scenereleases AS a
        movie rip (2.Days.in.The.Valley.1996.DVDRip.XviD-iND);
        Portishead-Only_You as GP_Wu-1st_Thing_First; DJ_BK-Tape_40
        as Anthony_B-Black_Survivor. In every case a second, unrelated
        but real srrDB-verified metadata set happened to sit in the
        same folder, and the self-referential .sfv for the real local
        audio got picked for the actual CRC check instead. Now the
        .sfv whose filename matches the CANONICAL release name is
        selected explicitly; if the real audio doesn't actually match
        that canonical release's content, CRC check now correctly
        fails and the release goes to incomplete for manual review,
        instead of silently "passing" a meaningless self-check.
  v2.12 BUGFIX: check_metadata_crcs() treated EVERY metadata file
        the downloaded SRR declares as blocking, even one that has
        nothing to do with this release at all. Confirmed via a real
        case: the SRR for The_High_and_Mighty-Home_Field_Advantage-
        Reissue-VINYL-2024-CMS also declared a second .m3u entry for
        a completely unrelated release ("Aestro_and_Salvatore_Papa-
        Feel_You_EP..."), apparently bundled in by mistake on
        srrDB's own side. That stray entry extracts as an empty
        0-byte file (its real content was never actually part of
        this archive), which check_metadata_crcs flagged as "META
        CRC EMPTY" and counted as a mismatch — even though the
        release's own NFO, JPG, SFV, and its real M3U all passed
        cleanly. One unrelated leftover was enough to route an
        otherwise fully valid release to incomplete. Now compares
        each declared entry's filename against the canonical release
        name (reusing the same _normalize_stem() matching from the
        v2.11 SFV-selection fix); entries that are clearly unrelated
        are logged as "META CRC FOREIGN (ignored...)" and no longer
        block the release, while a genuine problem with the
        release's OWN metadata still correctly fails it.
  v2.13 Console output now flushes on every log line (print(...,
        flush=True)), matching what the log file already did. Python
        block-buffers stdout when it's not a real terminal (piped,
        redirected, or run via "docker exec" without a TTY), so
        output was appearing in delayed chunks even though releases
        were actively being processed in the background the whole
        time — purely cosmetic, no change in behavior, just real-time
        visibility into progress.
  v2.14 Removed the SQLite processing-history DB entirely (PROC_DB,
        proc_db_connect, init_archive_db, proc_db_write, the
        ARCHIVE_OUTPUT_DIRS init-scan). It had been write-only for a
        long time — dupe detection and every other decision has been
        folder-based against scenereleases/ since v2.0, and the only
        read against the DB was the init-scan's own dedup check, not
        anything feeding a real decision. Each run's outcome is still
        collected in-memory for the end-of-run summary/results log
        via the new record_result(), just without the per-run DB
        connect/init/write/close overhead — startup is faster since
        the archive-wide init scan across every output folder no
        longer runs on every single launch, and the code is smaller.
  v2.15 Optional integration with the new ArchiveDB web browser
        (search UI over scenereleases/): if ARCHIVEDB_URL is set, a
        POST to {ARCHIVEDB_URL}/reindex is sent once at the very end
        of the run, so the search index picks up whatever this run
        just changed without waiting for a manual reindex. Disabled
        by default (empty ARCHIVEDB_URL); any failure is only logged,
        never fatal — this is a nice-to-have refresh of a separate,
        independent search index, not something the archive itself
        depends on.
  v2.16 New: cleanup_usenet_junk() strips leftover .nzb/.html/.htm/
        .srr files right before every single move, regardless of
        outcome (scene, incomplete, nomatch, dupes) — these sometimes
        come bundled in with "unclean" downloads pulled straight from
        Usenet and aren't part of the actual Scene release. Hooked
        into move_release() and move_to_dupes(), the two functions
        every move in the whole script ultimately goes through, so
        every destination is covered from one place rather than
        needing a call at each individual move site. Respects
        DRY_RUN like everything else — logs what would be removed
        without touching anything.
  v2.17 New: Stage 1b — audio CRC search. Stage 1 (stem search) only
        ever accepted a srrDB result if its NAME matched the local
        stem exactly (or, with exactly one result, matched closely
        enough to tolerate a missing country tag). A messy Usenet
        folder with no group tag anywhere (e.g. "Jeru The Damaja -
        The Real Hip Hop Best Of D & D Studios Vol. 1") can legitimately
        turn up several textually-different srrDB candidates for the
        same stem, none of which match by name, so Stage 1 gave up
        even though the release really was on srrDB. Confirmed by
        hand: a search on such a stem returned 4 differently-named
        candidates, and comparing actual audio CRCs against each one
        showed exactly one was a byte-for-byte match.
        Stage 1b now runs right after Stage 1 fails: it reuses the
        very same srrDB search results (per-run cache, no extra
        requests), and for each candidate release fetches its file
        list (srrdb_details — an API call, not a full SRR download,
        unless srrDB's own details endpoint 404s) and compares the
        CRCs of its audio files against the real local media files'
        CRCs. If exactly one candidate's audio content matches
        completely, that candidate is accepted as the canonical
        release, exactly as if Stage 1 had matched it by name. Zero
        or multiple full content matches fall through to Stage 2/3
        as before — this never guesses, it only accepts a candidate
        when the audio itself proves it beyond doubt. Capped at
        AUDIO_CRC_MAX_CANDIDATES (default 8) candidates to avoid
        hammering srrDB on a hopelessly generic/ambiguous stem.
  v2.18 Stage 1b now also searches using the raw ON-DISK FOLDER NAME,
        not just NFO/SFV/M3U filename stems. A folder containing
        nothing but loose MP3s (e.g. "Jeru The Damaja - Divine Design
        - 2003 - Ksi", no .sfv/.nfo/.m3u at all) has no metadata file
        to build a stem from, so raw_stems was empty and Stage 1b
        used to exit immediately without even trying — even though
        the folder name itself, pasted straight into srrDB's search,
        finds the exact right release by hand. Stage 1b now always
        includes the folder name as one more search candidate
        alongside any metadata stems, so a bare pile of correctly-
        named MP3s with no SFV can still be verified and matched by
        real audio CRC content, exactly like a folder that does have
        metadata files.
  v2.19 BUGFIX: the console/log startup banner ("INCOMING PROCESSOR
        vX.XX [...]") was a separate hardcoded string that never got
        touched when bumping the real version at the top of this file
        — confirmed for real: a live run on v2.18 still printed
        "v2.16" at startup, even though every behavioral change since
        then (Stage 1b, the folder-name fallback) was genuinely
        present and working. The banner now reads from a single
        SCRIPT_VERSION constant in the configuration block, so from
        here on bumping the version number in exactly one place (and
        adding the matching entry here) keeps the banner honest —
        there's no second copy left to forget.
  v2.20 BUGFIX: a real dotted-acronym release, "C.O.N.G.O-C.O.N.G.O-
        2001-EGO", existed on srrDB under EXACTLY that name (confirmed
        by hand on the site) yet was missed entirely and routed to
        nomatch. Root cause: srrDB's own search tokenizes a name like
        "C.O.N.G.O" into a run of single-letter tokens, so a query for
        it (whether the folder name or a metadata stem) comes back
        with a huge, noisy, differently-ranked result page — the
        genuinely correct entry can simply not be in THAT ONE query's
        result page at all, even though it's on srrDB. Stage 0 and
        Stage 1 each only ever check their own single query's own
        results for a literal exact-name match, so both missed it
        independently; Stage 1b then saw 78 merged-but-still-
        incomplete-per-query candidates and gave up without checking
        any of them, since that count was over its CRC-check safety
        cap. Stage 1b now checks the FULL merged candidate pool
        (combined across every query it already ran) for a literal
        exact-name hit BEFORE the cap/CRC step — cheap (just a string
        compare against names already in hand) and exactly as trusted
        as what Stage 0/1 already do, just no longer blind to a hit
        that only showed up in a different query's result page than
        the one being checked.
  v2.21 BUGFIX (real root cause of the C.O.N.G.O case, v2.20's fix
        alone wasn't enough): confirmed by rerunning after v2.20 that
        the exact release name never showed up in ANY of the three
        /search queries' own results at all — not "spread across
        different queries" as v2.20 assumed, but genuinely absent from
        every one of them. srrDB's /search endpoint tokenizes a name
        like "C.O.N.G.O" into single letters and apparently doesn't
        surface the real release for any of the resulting wildcard-
        heavy queries, no matter how they're combined. srrdb_search_
        exact() (used by both Stage 0 and Stage 1) now falls back to a
        direct /v1/details/<name> lookup whenever the /search-based
        checks find nothing — that endpoint is a plain, non-fuzzy,
        exact-name database lookup (the same one already used elsewhere
        to fetch a confirmed release's file list), completely
        unaffected by the search tokenizer, so it finds the release
        directly by its exact name regardless of how badly /search
        mangles the query. Costs one extra HTTP request, but only ever
        on the failure path (search already found nothing), so normal,
        cleanly-matching releases are unaffected.
  v2.22 New: post_discord_report() posts a summary of every run to a
        Discord channel via an incoming webhook, if DISCORD_WEBHOOK_URL
        is set (empty/unset = disabled, same pattern as ARCHIVEDB_URL).
        Covers everything, not just successes: scenereleases, dupes,
        incomplete, nomatch (both variants), mp3s, and anything left in
        incoming for manual review, plus a small breakdown of which
        search stage found each match. Built as a single Discord embed
        with a monospace overview block up top (readable at a glance on
        a phone) and one field per non-empty destination listing the
        actual release names underneath (readable on desktop too, since
        fields wrap sensibly at both widths). Colored orange when a run
        produced anything that needs a human look (incomplete, nomatch/
        _invalid, or left in incoming) and green for a fully clean run.
        Skips posting entirely for an empty run (0 folders to process)
        by default — DISCORD_SKIP_EMPTY_RUNS controls that. A failed or
        unconfigured webhook only logs a line, it never fails the run
        itself; the archive processing is entirely unaffected either way.
  v2.23 Discord report: each listed release now shows only the clean
        srrDB release name (once one is known), not the original messy
        incoming folder name — feedback after seeing it live was that
        the folder name adds nothing once it's already been resolved
        and just makes the report noisier to read. Entries with no
        resolved name at all (mp3s, nomatch, left-in-incoming — nothing
        to clean up to) still show the folder name, since that's all
        there is.
  v2.24 Discord report reworked after seeing it live: release names
        were wrapping mid-word because Discord caps an embed FIELD's
        rendered width at a small, fixed value no matter the screen
        size — the "Wie erkannt" stage-count box is dropped (the
        "Ergebnis" overview and the per-destination lists were enough),
        and the release-name lists now go into the message's plain
        *content* instead of embed fields. Plain content reflows like
        any ordinary chat message, wide on desktop and narrower on a
        phone, exactly the "adapts to the screen" behavior asked for,
        with nothing for us to hardcode. Only the small numeric
        overview stays in an embed, since a fixed-width code block is
        actually wanted there for column alignment. Content is capped
        at 2000 characters per Discord message, so a large run's lists
        are now split across multiple sequential messages if needed
        (build_discord_messages), packing as much as fits into each
        one rather than one destination per message.
  v2.25 BUGFIX: confirmed live that v2.24's split (overview in an
        embed, release lists in plain content) rendered in the wrong
        order — a run's single dupe entry appeared ABOVE the
        "Ergebnis" summary box that was meant to introduce it. Root
        cause: Discord always renders a message's plain content above
        any embed attached to it, regardless of the order fields are
        sent in the payload, so splitting the report across content
        and an embed can never produce a controlled reading order.
        The report is now plain content only, no embed at all, built
        as one ordered block (title, overview, then each destination's
        list) — the only way to actually control what appears where.
        The former embed color bar (green/orange) is now a ✅/⚠️ right
        in the title line, and the former embed footer is now a small
        subtext line ("-# ...") at the end of the report.
  v2.26 Two more bugs found live right after v2.25 shipped:
          - Underscore-heavy release names (the Scene naming norm —
            "Artist_Name-Title-2001-GRP") rendered with random broken
            mid-name italics ("DJPremier" instead of "DJ_Premier",
            etc.), because Discord's markdown treats "_word_" as an
            italics marker. _discord_escape() now backslash-escapes
            markdown special characters (_ * ~ ` | > and backslash
            itself) in every dynamic value (release name, folder name,
            failure reason) before it goes into the report — never in
            our own literal **bold**/-# markup, only in the data.
          - Losing the embed in v2.25 also lost its visual "card"
            look — plain content just floats loose in the channel with
            nothing setting it apart. Each message now opens with
            ">>> ", turning the rest of it into a Discord blockquote
            (an indented block with a left-edge bar), which gives the
            report a boxed look again without needing an embed.
  v2.27 REVERTED the plain-content redesign from v2.24/v2.25 back to a
        single colored embed, per direct feedback after seeing both
        live: the blockquote (">>> ") from v2.25/v2.26 does not give
        Discord's colored left-edge bar or card background — only a
        real embed does that, and the boxed look mattered more than
        avoiding the occasional wrapped release name in a field. Back
        to one embed (green/orange) with "Ergebnis" + one field per
        destination, same as v2.22/v2.23, but keeping every real fix
        found along the way: clean srrDB names instead of the messy
        original folder name (v2.23), and markdown-escaping of every
        dynamic value so underscore-heavy Scene names never render
        with broken mid-name italics again (v2.26). "Wie erkannt" stays
        gone, as asked.
  v2.28 BUGFIX: extract_srr() (runs when a matched release's metadata
        CRC-fails and the SRR is pulled down to restore the original
        nfo/m3u/sfv) only ever logged result.stdout from the "srr.py -x
        -y" subprocess — the return code was never checked and stderr
        was discarded entirely. Confirmed via a real case
        (Nas-It_Aint_Hard_To_Tell_(Pj-Edit)-2003-DGN): the SRR
        downloaded fine, "SRR EXTRACT:" logged with zero output lines
        after it, and the metadata re-check immediately after showed
        the EXACT SAME three CRC mismatches as before extraction —
        meaning srr.py never actually touched the files, and nothing in
        the log explained why. srr.py is a Python 2 script historically;
        if "python" resolves to Python 3 here, the subprocess can fail
        outright (bad interpreter / import error) with the real reason
        going only to stderr, previously discarded. extract_srr() now
        returns True/False for "did extraction actually run and
        succeed", logs the return code and every stderr line whenever
        it's non-zero, and catches FileNotFoundError explicitly instead
        of letting it propagate. The caller now logs an explicit WARNING
        when extraction didn't succeed, so a CRC-mismatch-after-
        extraction case is immediately distinguishable in the log from
        "extraction silently did nothing" instead of looking identical.
        The same missing-returncode-check existed in
        srrdb_details_from_srr()'s "srr.py -l" call (used when srrDB's
        own details API 404s or returns an empty list) and is fixed the
        same way. IMPORTANT: this only makes the failure visible, it
        does not by itself fix a broken "python" interpreter — if the
        next run still shows "EXTRACT FAILED" / "srr.py -l failed" in
        the log, that error message (and its exit code) is the next
        thing to look at, most likely by checking "python --version"
        and "python2 --version" / "python3 --version" inside the
        rescene-worker container to see what "python" actually resolves
        to versus what srr.py was written for. Every release currently
        sitting in incomplete/ that failed via this exact silent path
        should be moved back into incoming/ and reprocessed once the
        underlying interpreter issue (if that's what this turns out to
        be) is confirmed and fixed, since its metadata may have been
        genuinely fine all along.
  v2.29 ROOT CAUSE FOUND for the v2.28 case, via a standalone diagnostic
        script that re-ran srrdb_details() / check_metadata_crcs() /
        download_srr() / extract_srr() against the real folder in
        isolation (safe to run alongside a long main run, since it never
        touches LOCKFILE): extract_srr() now correctly surfaced the real
        failure, which was neither a bug in our subprocess handling nor
        bad data in the SRR (confirmed separately by manually extracting
        the actual .srr file with a clean checkout of pyrescene's own
        srr.py: all three CRCs matched srrDB's "expected" values exactly).
        The real cause: "PermissionError: [Errno 13] Permission denied"
        from srr.py's own "open(out_file, 'wb')", while trying to write
        "00-Nas-It_Aint_Hard_To_Tell_(Pj-Edit)-2003-DGN.nfo" -- the
        EXISTING local file was "00-nas-it_aint_hard_to_tell_(pj-edit)-
        2003-dgn.nfo", same name, different letter case entirely. This
        archive runs on a CIFS/SMB mount from Unraid, which resolves
        lookups/opens case-insensitively (confirmed: check_metadata_crcs
        found and CRC-checked the lowercase file perfectly fine via its
        canonically-cased path, reporting MISMATCH rather than MISSING),
        but writing the canonically-cased name while the differently-
        cased file still exists is effectively creating a second,
        colliding directory entry from the SMB server's perspective --
        not a same-name overwrite -- which is exactly what got denied.
        This is also why the .sfv extracted fine in the same folder: no
        differently-cased .sfv existed locally beforehand, so that write
        was a clean create with nothing to collide with.
        New normalize_metadata_case(): for every metadata file srrDB
        expects, if a local file exists under a different case, it's
        renamed in place to the exact canonical case via the existing
        rename_case_safe() (already built for exactly this CIFS case-
        only-rename quirk, previously only used for the folder itself
        and for renaming media files by CRC) -- called right after the
        folder rename, before the metadata CRC check and before any SRR
        extraction, so a later extraction is always a normal same-name
        overwrite and never a case-colliding create.
  v2.30 FURTHER ROOT CAUSE FOUND, v2.29 alone wasn't the whole story:
        confirmed live on a SECOND real case (Nas-Mastermind_BW_Book_Of_
        Rhymes_(VLS)-2003-BKE) that extraction can fail with the exact
        same PermissionError even when there is NO case mismatch at all
        -- srrDB's own expected filenames were already lowercase here,
        matching the local files exactly, so normalize_metadata_case()
        correctly found nothing to fix, yet extract_srr() still hit
        "Permission denied" trying to overwrite the SAME exact filename.
        Confirmed directly on the Docker host that this is NOT specific to
        srr.py at all: a plain shell "echo test > <existing file>"
        against that same file failed identically, and against a
        completely unrelated, brand-new test file too. Also confirmed
        that "mount | grep archive" shows this archive is mounted over
        CIFS from Unraid with Unix extensions disabled ("nounix"), which
        is why "ls -la" always shows a flat 0755 for every file
        (file_mode=0755 mount option) regardless of anything real, and
        why a chmod from the container side does nothing at all
        (confirmed live: chmod 444 then chmod 644 on a test file changed
        nothing -- the second write attempt still failed). The Unraid
        share's own SMB permissions for the mount's user were confirmed
        to be a plain Read/Write, ruling out a share-level permission
        problem too.
        What DOES reliably work on this mount, confirmed live: deleting
        an existing file. New clear_metadata_for_extract(), called right
        before extract_srr() (after normalize_metadata_case(), so a
        prior case fix still applies first): removes each metadata file
        srrDB is about to resupply, so what srr.py actually performs is
        always a plain file CREATE, which has been confirmed to work
        cleanly on this mount in every single test so far, rather than
        an in-place overwrite, which this mount appears to deny
        outright regardless of case, origin, or Unix mode bits. If a
        file fails to be recreated for some unrelated reason (network
        hiccup, etc.), check_metadata_crcs() afterwards reports it as
        MISSING rather than MISMATCH -- no worse than before, and
        clearer about what actually happened.
  v2.31 Every srrDB request used to go straight through the VPN tunnel
        (rescene-worker ran with "--network container:<vpn-container>"),
        which is noticeably slower than a direct connection and was not
        actually needed most of the time -- the VPN is only useful once
        srrDB starts returning HTTP 429/403/503 for this IP. Now
        rescene-worker runs on its own normal network and talks to
        srrDB directly (the real IP) by default. _srrdb_request() only
        switches to routing through gluetun's built-in HTTP proxy (see
        VPN_PROXY_URL below) the first time it actually sees a block
        code, logs that switch once, and then stays on the proxy for
        the rest of this run -- no container rebuild needed mid-run,
        and no manual IP-rotation step required just to get started.
        If VPN_PROXY_URL is not set, behaviour is unchanged from v2.30
        (a block code aborts the run immediately, same as before).
  v2.32 BUGFIX: Discord report failed outright on a big run ("HTTP 400:
        Embed size exceeds maximum size of 6000") -- each field's VALUE
        was already capped at 1024 chars (Discord's own per-field
        limit), but Discord also caps the EMBED AS A WHOLE (title +
        every field name/value + footer, all added together) at 6000
        chars, and that total was never tracked. A run of ~1200
        releases spread across several destinations easily produced
        more than 6000 chars total even with every individual field
        staying under 1024, and the whole report was then rejected,
        not just trimmed. build_discord_messages() now tracks a
        running total as it adds fields and, once DISCORD_EMBED_TOTAL_CAP
        would be exceeded, stops adding further per-destination fields
        and appends one final "not shown" note
        field instead, naming the skipped destinations and their
        counts -- the report always gets posted, worst case with fewer
        of the long per-release lists and a pointer to the logfile for
        the rest.
  v2.33 FOLDER LAYOUT CHANGE: the "nomatch" folder is now called
        "scenereleases_nosrr". What lands there are real Scene
        releases (SFV present, CRC clean) that srrDB simply doesn't
        list -- "nomatch" suggested something went wrong, which it
        didn't. nomatch/_invalid is retired and no longer filled: a
        release with no srrDB match, an SFV, a non-Scene-like name and
        FAILED CRCs (result code NOSCENE_FAIL) now goes to incomplete
        like every other CRC-failed release (NOMATCH_INCOMPLETE
        already did). Constants: NOMATCH_DIR -> NOSRR_DIR,
        NOSCENE_DIR -> NOSRR_DIR, NOSCENE_INVALID_DIR removed.
        Internal result codes (NOMATCH_OK, NOSCENE_FAIL, ...) are
        unchanged on purpose, only their destination labels changed.
        EXISTING DATA is NOT touched by this script: run
        migrate_nomatch_to_nosrr.py once (dry run first) to rename
        /archive/nomatch and move nomatch/_invalid/* into incomplete.
        The Discord report and summary use the new folder names.
  v2.34 Result order in the end-of-run summary and the Discord report
        changed to: scenereleases, scenereleases_nosrr, dupes,
        incomplete, then mp3s and left-in-incoming. Before, incomplete
        and dupes came right after scenereleases. Only the display
        order in _group_run_results() changed (shared by both outputs),
        nothing about routing or counting.

  v3.0  NEW FOLDER LAYOUT with three scene folders:
          scenereleases_srr     real folders: releases verified against srrDB
          scenereleases_nosrr   real folders: clean releases srrDB does not list
          scenereleases         ONLY relative symlinks to the two above
                                (../scenereleases_srr/<name> or
                                ../scenereleases_nosrr/<name>), the one
                                collection of all clean releases
        The processor now moves verified releases to scenereleases_srr
        (before: scenereleases) and creates the matching symlink in
        scenereleases right after every move into scenereleases_srr or
        scenereleases_nosrr. Dupe detection looks at scenereleases, so it now
        covers BOTH real folders in one place; move_release() additionally
        treats an existing name in scenereleases as a dupe for both targets.
        Summary and Discord report use the destination names
        scenereleases_srr and scenereleases_nosrr.

  v3.1  Log files now go to /app/logs (host: appdata/rescene-worker/logs)
        instead of /app. The folder is created automatically. Affects
        incoming_processor_<mode>_<ts>.log and incoming_results_<mode>_<ts>.log.
        SAFETY CHECK at start: the run is refused if scenereleases still
        contains real folders or scenereleases_srr is missing, i.e. before
        migrate_to_v3_layout.py has been run. Symlinks can only be
        created where the archive is a local folder (the file server since the
        move of rescene-worker), not over CIFS.
        Maintenance: sync_scene_links.py repairs links (missing, dangling,
        wrong target) after manual moves.

  v3.2  Portable Edition for use outside the original environment:
          - All paths and switches can now be set via environment variables
            (INCOMING_DIR, ARCHIVE_ROOT, LOG_DIR, LOCKFILE, SRR_PY,
            DRY_RUN, REQUEST_DELAY); the defaults are the old values, so
            existing setups keep working without any change.
          - New command line flag --dry-run (same as DRY_RUN=1).
          - srr.py is started with the same Python interpreter that runs
            this script (sys.executable) instead of a hardcoded "python".
          - The SETUP section below was rewritten: it still described the
            v2.0 layout, a SQLite history database (removed in v2.14) and
            srrDB cookies (never needed by the code).
          - Companion tools: migrate_to_v3_layout.py (old layout -> v3
            layout, dry run by default) and sync_scene_links.py.

  v3.3  Language: the Discord report and the layout check hints are now in
        English ("Result", "Note", "release(s) processed"); the layout check
        points to tools/migrate_to_v3_layout.py (the old text named a
        script that does not exist). No change in behaviour.

Processes all folders inside INCOMING_DIR using a multi-stage pipeline:

  Stage 0  — Exact folder name match against srrDB
  Stage 1  — Stem search (exact, from metadata filenames like 00-artist-title.nfo)
  Stage 1b — Audio CRC search (when Stage 1 finds several textually-different
             candidates for the same stem, accept one only if its audio CRCs
             fully match the local media files — see v2.17 above)
  Stage 2  — Fuzzy search (space-tokens from folder name, requires year)
  Stage 3  — ID3/NFO fallback (album+year+group from tags/nfo)
  → On srrDB match: full Scene workflow (metadata CRC, SRR if needed, media CRC, rename)
  → No match + SFV + Scene-like name  → scenereleases_nosrr / incomplete
  → No match + SFV + no Scene name    → scenereleases_nosrr / incomplete
  → No match + no SFV + Scene name    → left in incoming (manual review)
  → Only mp3s, no SFV, no Scene name  → mp3s

Set DRY_RUN = True to preview without moving/renaming anything.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SETUP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. DEPENDENCIES

       pip install requests mutagen pyrescene

     pyrescene provides srr.py (https://github.com/srrDB/pyrescene).
     Point SRR_PY to it (default /usr/local/bin/srr.py). The easiest way
     is the Dockerfile that ships with this project (see processor/).

  2. CONFIGURATION — environment variables (all optional, defaults in brackets)

       INCOMING_DIR    folder where new releases land   [/archive/incoming]
       ARCHIVE_ROOT    root of the archive              [/archive]
       LOG_DIR         where run logs are written       [/app/logs]
       LOCKFILE        prevents parallel runs           [/app/incoming_processor.lock]
       SRR_PY          path to srr.py                   [/usr/local/bin/srr.py]
       DRY_RUN         1 = preview only, no changes     [0]   (or --dry-run)
       REQUEST_DELAY   seconds between srrDB calls      [1.0]
       VPN_PROXY_URL   HTTP proxy used only after srrDB blocked the real IP
       ARCHIVEDB_URL   e.g. http://archivedb:8000 — reindex after each run
       DISCORD_WEBHOOK_URL   run report to a Discord channel
       DISCORD_SKIP_EMPTY_RUNS   skip the report when nothing was processed

  3. FOLDER STRUCTURE under ARCHIVE_ROOT (v3 layout; created automatically
     where missing, except that an existing old layout is refused, see below)

       incoming/             ← INCOMING_DIR, new releases land here
       scenereleases_srr/    ← real folders: releases verified against srrDB
       scenereleases_nosrr/  ← real folders: clean releases srrDB does not list
       scenereleases/        ← ONLY relative symlinks to the two folders above
       incomplete/           ← CRC fails / missing files
       dupes/                ← duplicates and superseded old versions
       mp3s/                 ← loose media files without SFV

     Symlinks need a local filesystem (not CIFS/SMB). Run the processor on
     the machine that owns the disks, or in a container with the folder
     mounted locally. If the archive still has the old layout, the run is
     refused; convert it once with migrate_to_v3_layout.py (dry run first).

     Dupe handling: scenereleases is the single source of truth. A release
     is a dupe if its canonical name already exists there. Dupes get a
     counter suffix: ReleaseName.1, ReleaseName.2, ...

  4. srrDB — search and SRR download work anonymously, no login needed.
     Be polite: REQUEST_DELAY spaces the requests out.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import sys
import re
import time
import zlib
import fcntl
import signal
import datetime
import subprocess
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# ★ CONFIGURATION — set via environment variables (see SETUP above) ★
INCOMING_DIR  = os.environ.get("INCOMING_DIR", "/archive/incoming")   # folder where new releases land
ARCHIVE_ROOT  = os.environ.get("ARCHIVE_ROOT", "/archive")            # root of your archive

# v3 layout: scenereleases holds ONLY symlinks, the real folders are
# scenereleases_srr (srrDB verified) and scenereleases_nosrr.
SCENE_DIR              = os.path.join(ARCHIVE_ROOT, "scenereleases")      # v3.0: ONLY symlinks
SRR_DIR                = os.path.join(ARCHIVE_ROOT, "scenereleases_srr")  # v3.0: real folders, srrDB verified
INCOMPLETE_DIR         = os.path.join(ARCHIVE_ROOT, "incomplete")
NOSRR_DIR              = os.path.join(ARCHIVE_ROOT, "scenereleases_nosrr")  # v2.33, was "nomatch"
NOMATCH_INCOMPLETE_DIR = INCOMPLETE_DIR                       # merged
MP3S_DIR               = os.path.join(ARCHIVE_ROOT, "mp3s")


def _env_flag(name, default=False):
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


DRY_RUN       = _env_flag("DRY_RUN") or ("--dry-run" in sys.argv)   # True = preview only
REQUEST_DELAY = float(os.environ.get("REQUEST_DELAY", "1.0"))       # seconds between srrDB API calls

SCRIPT_VERSION = "3.3"  # ← single source of truth for the startup banner;
                          #   bump this alongside the version-history entry
                          #   at the top of the file so they can never drift
                          #   apart again (see v2.19 below)

AUDIO_CRC_MAX_CANDIDATES = 8   # ← Stage 1b: max ambiguous srrDB candidates to
                                #   CRC-check per release before giving up and
                                #   falling through to Stage 2/3 (keeps a very
                                #   generic/short stem from triggering a pile
                                #   of srrDB lookups for one release)

METADATA_EXTENSIONS = {".nfo", ".sfv", ".m3u", ".jpg"}
MEDIA_EXTENSIONS    = {".mp3", ".flac", ".ogg", ".m4a", ".wav", ".ape", ".m2v", ".mpg", ".mpeg"}

FORMAT_TAGS = {
    'lp', 'ep', 'vls', 'cds', 'cdm', 'vinyl', 'promo', 'retail',
    'reissue', 'remaster', 'bootleg', 'advance', '12inch', '7inch',
    'dvda', 'dvd', 'tape', '2lp', '3lp', 'cd', '2cd', '3cd',
}

LOCKFILE = os.environ.get("LOCKFILE", "/app/incoming_processor.lock")  # lockfile to prevent parallel runs
SRR_PY   = os.environ.get("SRR_PY", "/usr/local/bin/srr.py")           # path to srr.py from the pyrescene project

# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

stats = {
    "exact_match":   0,
    "stem_match":    0,
    "audio_crc_match": 0,
    "fuzzy_match":   0,
    "id3_match":     0,
    "no_match":      0,
    "scene":         0,
    "incomplete":    0,
    "nomatch_ok":    0,
    "nomatch_fail":  0,
    "noscene_ok":    0,
    "noscene_fail":  0,
    "mp3s":          0,
    "left_alone":    0,
    "skipped":       0,
    "srr_downloads": 0,
}

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    _shutdown = True
    print("\n!!! Signal received — finishing current release then stopping ...")


signal.signal(signal.SIGINT,  _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
mode_tag  = "DRY" if DRY_RUN else "LIVE"
LOG_DIR   = os.environ.get("LOG_DIR", "/app/logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOGFILE   = os.path.join(LOG_DIR, f"incoming_processor_{mode_tag}_{timestamp}.log")
RESULTS_FILE = os.path.join(LOG_DIR, f"incoming_results_{mode_tag}_{timestamp}.log")
_log_fh   = open(LOGFILE, "a", encoding="utf-8")
sys.stderr = _log_fh


def log(msg):
    print(msg, flush=True)
    _log_fh.write(msg + "\n")
    _log_fh.flush()


class ApiBlockedError(Exception):
    pass

# ---------------------------------------------------------------------------
# srrDB API helpers
# ---------------------------------------------------------------------------

HEADERS     = {"User-Agent": "scene_cleaner/3.9 (personal archive tool)"}
BLOCK_CODES = {403, 429, 503}

# v2.31: by default every request below goes out directly on this
# machine's real IP. Only once srrDB actually returns a block code do
# we switch to routing through gluetun's built-in HTTP proxy (see
# new_ip.sh / README for the "HTTPPROXY=on" gluetun setup) -- and then
# we stay on it for the rest of this run, since a block tends to apply
# for a while and there is no point bouncing back and forth.
VPN_PROXY_URL = os.environ.get("VPN_PROXY_URL", "")  # e.g. "http://gluetun:8888"
_use_vpn_proxy = False


def _current_proxies():
    if _use_vpn_proxy and VPN_PROXY_URL:
        return {"http": VPN_PROXY_URL, "https": VPN_PROXY_URL}
    return None

SCENE_NAME_RE = re.compile(
    r'^[A-Za-z0-9_.()&\[\]+,\'\-]+-[A-Za-z0-9_.()&\[\]+,\'\- ]+-\d{4}-[A-Za-z0-9_]+$'
)


def has_scene_name(folder_name):
    return bool(SCENE_NAME_RE.match(folder_name))


def extract_year(s):
    m = re.search(r'[-_](\d{4})[-_]', s)
    return m.group(1) if m else None


def extract_group(s):
    m = re.search(r'-([A-Za-z0-9_]{2,12})$', s)
    return m.group(1).upper() if m else None


def folder_to_tokens(name):
    s = name.replace("_", " ").replace("-", " ").replace(".", " ")
    s = re.sub(r'\(.*?\)', '', s)
    tokens = re.split(r'\s+', s.strip())
    return [t for t in tokens if len(t) > 2 or re.match(r'\d{4}', t)]


def _strip_numeric_prefix(stem):
    return re.sub(r'^\d{1,3}[-_]', '', stem)


def _normalize_double_dash(s):
    return re.sub(r'--+', '-', s) if '--' in s else None


# ---------------------------------------------------------------------------
# Stage 1: Stem search (exact match via metadata filenames)
# ---------------------------------------------------------------------------

def _tokens_match(a, b):
    def tok(s):
        return set(re.split(r'[-_\s]+', s.lower()))
    return tok(a) == tok(b)


# Country/language tags that Scene NFO writers sometimes omit from the
# release name even though srrDB's canonical name includes them, e.g.
# "Irre_Locke-...-VLS-1998-KrbZ" locally vs the real
# "Irre_Locke-...-VLS-DE-1998-KrbZ" on srrDB. A single missing/extra
# tag like this is common enough that an otherwise-perfect single
# srrDB result was being silently thrown away by strict token equality.
COUNTRY_TAGS = {
    "de", "us", "uk", "fr", "nl", "es", "it", "jp", "se", "no", "dk", "fi",
    "at", "ch", "be", "ca", "au", "pl", "cz", "ru", "br", "mx", "kr", "cn",
    "in", "ie", "pt", "gr", "hu", "ro", "bg", "hr", "si", "sk", "lt", "lv",
    "ee", "tr", "za", "nz",
}


def _tokens_match_lenient(a, b):
    """
    Like _tokens_match, but also accepts the case where the token sets
    differ by exactly one token AND that token is a known country or
    language code. Only ever used when srrDB returned a single result
    for the search, so the risk of a false positive is very low —
    there's no competing candidate to confuse it with.
    """
    def tok(s):
        return set(re.split(r'[-_\s]+', s.lower()))
    ta, tb = tok(a), tok(b)
    if ta == tb:
        return True, None
    diff = ta ^ tb
    if len(diff) == 1:
        tag = next(iter(diff))
        if tag in COUNTRY_TAGS:
            return True, tag
    return False, None


MAX_RETRIES = 3  # attempts per HTTP request on timeouts / 5xx errors

_SEARCH_CACHE = {}  # query.lower() -> list of raw srrDB results (per run)


def _srrdb_request(url, timeout=12):
    """
    Central HTTP GET with retry and exponential backoff.
    Retries on connection errors, timeouts and 5xx responses.

    v2.31: on a block code (403/429/503), if VPN_PROXY_URL is set and
    we are not already using it, this switches _use_vpn_proxy to True,
    logs it once, and retries the SAME request through the proxy
    instead of giving up right away -- that switch then stays in
    effect for every later call in this run (see _current_proxies()).
    Only raises ApiBlockedError if we are already on the proxy (or no
    proxy is configured at all) and still get blocked, same as v2.30.
    """
    global _use_vpn_proxy
    delay = REQUEST_DELAY
    last_exc = None
    r = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            time.sleep(delay)
            r = requests.get(url, headers=HEADERS, timeout=timeout,
                              proxies=_current_proxies())
        except requests.exceptions.RequestException as e:
            last_exc = e
            if attempt == MAX_RETRIES:
                raise
            log(f"  HTTP RETRY {attempt}/{MAX_RETRIES - 1} after error: {e}")
            delay = delay * 2 + 1
            continue
        if r.status_code in BLOCK_CODES:
            if VPN_PROXY_URL and not _use_vpn_proxy:
                log(f"  HTTP {r.status_code} on real IP -- switching to VPN "
                    f"proxy ({VPN_PROXY_URL}) for the rest of this run")
                _use_vpn_proxy = True
                return _srrdb_request(url, timeout=timeout)
            raise ApiBlockedError(f"srrDB blocked: HTTP {r.status_code}")
        if r.status_code >= 500 and attempt < MAX_RETRIES:
            log(f"  HTTP RETRY {attempt}/{MAX_RETRIES - 1} after HTTP {r.status_code}")
            delay = delay * 2 + 1
            continue
        return r
    return r


def _srrdb_search_results(query):
    """
    Query the srrDB search API, with per-run caching.
    Identical queries (Stage 0 vs Stage 1 stems vs Stage 2) hit the
    network only once. Transient failures are not cached.
    """
    key = query.lower()
    if key in _SEARCH_CACHE:
        log(f"  SEARCH CACHE HIT: {query!r}")
        return _SEARCH_CACHE[key]
    try:
        r = _srrdb_request(
            f"https://api.srrdb.com/v1/search/{requests.utils.quote(query)}"
        )
    except ApiBlockedError:
        raise
    except Exception as e:
        log(f"  SEARCH ERROR: {e}")
        return []
    if r is None or r.status_code != 200:
        _SEARCH_CACHE[key] = []
        return []
    try:
        results = r.json().get("results", [])
    except Exception:
        results = []
    _SEARCH_CACHE[key] = results
    return results


def srrdb_search_exact(stem):
    """
    Search srrDB for an exact stem match.

    Falls back to a direct /v1/details/<name> lookup when the /search
    endpoint's own results don't contain an exact match. This matters
    for short/dotted names like "C.O.N.G.O": srrDB's search tokenizes
    that into a run of single-letter wildcards, so a release that
    genuinely exists under this exact name can be entirely absent from
    THAT query's own result page (confirmed via a real case — the
    release existed on srrDB under the identical name, but never once
    showed up in any /search result for it). /v1/details/<name> is a
    direct, non-fuzzy, exact-name database lookup, unaffected by the
    search tokenizer, so it still finds it. Only tried once the search-
    based checks below have already failed, since it costs one extra
    HTTP request.
    """
    results = _srrdb_search_results(stem)
    if results:
        for result in results:
            if result["release"].lower() == stem.lower():
                return result["release"]
        if len(results) == 1:
            matched, tag = _tokens_match_lenient(stem, results[0]["release"])
            if matched:
                if tag:
                    log(f"  STEM MATCH via country/language-tag tolerance "
                        f"(missing/extra tag: '{tag}'): {stem!r} ~ {results[0]['release']!r}")
                return results[0]["release"]

    details = srrdb_details(stem)
    if details and details.get("name"):
        log(f"  EXACT MATCH via direct details lookup "
            f"(search API missed it): {stem!r} → {details['name']!r}")
        return details["name"]
    return None


def _build_stem_candidates(raw_stems):
    """
    Turns the raw metadata filename stems (NFO/SFV/M3U) into the list of
    search strings tried against srrDB: the stem itself, with its numeric
    track prefix stripped, and with any accidental double-dash collapsed
    — deduplicated, in a stable order. Shared by Stage 1 (exact match)
    and Stage 1b (audio CRC search), so both stages search against
    exactly the same candidate strings and reuse the same request cache.
    """
    seen = set()
    stems = []
    for s in sorted(raw_stems):
        stripped = _strip_numeric_prefix(s)
        normalized = _normalize_double_dash(s)
        normalized_stripped = _normalize_double_dash(stripped) if stripped else None
        for candidate in [s, stripped, normalized, normalized_stripped]:
            if candidate and candidate not in seen:
                seen.add(candidate)
                stems.append(candidate)
    return stems


def stage1_stem_search(folder_path, folder_name, raw_stems=None):
    """
    Extract stems from metadata filenames (NFO/SFV/M3U) and search srrDB exactly.
    Returns canonical release name or None.
    raw_stems can be passed in from scan_release_folder to avoid a re-walk.
    """
    if raw_stems is None:
        raw_stems = set()
        for root, _, files in os.walk(folder_path):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in {".nfo", ".sfv", ".m3u"}:
                    stem = os.path.splitext(f)[0]
                    raw_stems.add(stem)

    if not raw_stems:
        return None

    stems = _build_stem_candidates(raw_stems)
    log(f"  Stage 1 — stem search: {len(stems)} candidate(s)")

    for stem in stems:
        canonical = srrdb_search_exact(stem)
        if canonical:
            log(f"  STEM MATCH: {stem} → {canonical}")
            return canonical
        log(f"  STEM NO MATCH: {stem}")

    return None


# ---------------------------------------------------------------------------
# Stage 1b: Audio CRC search (content-based tie-break among ambiguous
# textually-different srrDB candidates that Stage 1 could not decide on
# by name alone — see v2.17 in the version history above)
# ---------------------------------------------------------------------------

def stage1b_audio_crc_search(folder_path, folder_name, raw_stems=None):
    """
    Runs only after Stage 1 has already failed to find a single
    name-exact match. Re-collects every srrDB search result already
    seen for this release's stems and for the raw on-disk folder name
    (served from the per-run search cache built during Stage 0/1 — no
    extra HTTP requests for the search itself), and for each distinct
    candidate release compares its audio files' real CRCs against the
    local media files' real CRCs.

    The folder name is always included as a search candidate, not
    just NFO/SFV/M3U stems — a folder containing nothing but loose
    MP3s (no metadata files at all) has no stem to build from
    otherwise, but the folder name alone is often enough to find the
    right srrDB candidates (see v2.18).

    A candidate is accepted ONLY if every local media file's CRC is
    present in that candidate's expected file list AND vice versa
    (same count, same CRCs) — i.e. the audio content is a complete,
    unambiguous match, not merely "some tracks overlap". If exactly
    one candidate satisfies this, it is returned as the canonical
    release. If zero or more than one candidate does, this returns
    None and the caller falls through to Stage 2/3 as before — this
    stage never guesses between competing candidates, it only ever
    accepts one when the audio itself proves there is no ambiguity.
    """
    if raw_stems is None:
        raw_stems = set()
        for root, _, files in os.walk(folder_path):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in {".nfo", ".sfv", ".m3u"}:
                    raw_stems.add(os.path.splitext(f)[0])

    stems = _build_stem_candidates(raw_stems) if raw_stems else []
    if folder_name not in stems:
        stems.append(folder_name)

    candidates = []
    seen_names = set()
    for stem in stems:
        for result in _srrdb_search_results(stem):
            name = result.get("release")
            if name and name not in seen_names:
                seen_names.add(name)
                candidates.append(name)

    if not candidates:
        return None

    # Exact-name pool check: Stage 0/1 already reject a candidate list
    # unless the search for ONE SPECIFIC stem returns it as a literal
    # exact match. But a short/generic stem (e.g. a dotted acronym like
    # "C.O.N.G.O", which srrDB's own search tokenizes into a pile of
    # single-letter wildcards) can return a huge, differently-ranked
    # result page for one query while a DIFFERENT query for the same
    # release (the folder name vs. a metadata stem) still happens to
    # surface the real entry. Since this stage already merges every
    # query's results into one pool, check that merged pool for a
    # literal exact-name hit before anything else — this is exactly
    # what Stage 0/1 already trust, just no longer scoped to whichever
    # single query happened to include it. A real hit here is name-for-
    # name identical to something we searched for, so it's accepted
    # immediately, without needing the audio CRC step and without being
    # subject to the ambiguous-candidate cap below (confirmed via a
    # real case: "C.O.N.G.O-C.O.N.G.O-2001-EGO" exists on srrDB under
    # that exact name, but no single query's own result page contained
    # it, so Stage 0/1 both missed it while it was sitting right there
    # in the combined pool).
    stem_lookup = {s.lower() for s in stems}
    for cand in candidates:
        if cand.lower() in stem_lookup:
            log(f"  EXACT NAME MATCH (found in merged candidate pool, missed by "
                f"Stage 0/1's per-query results): {cand}")
            return cand

    if len(candidates) > AUDIO_CRC_MAX_CANDIDATES:
        log(f"  Stage 1b — skipped: {len(candidates)} candidate(s) found, "
            f"too many to safely CRC-check (limit {AUDIO_CRC_MAX_CANDIDATES})")
        return None

    local_crc_map = build_crc_map(folder_path, MEDIA_EXTENSIONS)
    if not local_crc_map:
        return None

    log(f"  Stage 1b — audio CRC search: {len(candidates)} textually-different "
        f"candidate(s), checking real audio content against "
        f"{len(local_crc_map)} local media file(s)")

    full_matches = []
    for candidate in candidates:
        details = srrdb_details(candidate, folder_path)
        if not details:
            log(f"    {candidate}: details lookup failed — skipped")
            continue
        media_files = [
            f for f in details.get("files", [])
            if os.path.splitext(f.get("name", ""))[1].lower() in MEDIA_EXTENSIONS
            and len(f.get("crc", "")) == 8
        ]
        if not media_files:
            log(f"    {candidate}: no audio files in srrDB record — skipped")
            continue
        expected_crcs = {f["crc"].upper() for f in media_files}
        local_crcs = set(local_crc_map.keys())
        if expected_crcs == local_crcs and len(media_files) == len(local_crc_map):
            log(f"    {candidate}: {len(media_files)}/{len(media_files)} audio "
                f"file(s) match by CRC — FULL MATCH")
            full_matches.append(candidate)
        else:
            overlap = len(expected_crcs & local_crcs)
            log(f"    {candidate}: {overlap}/{len(local_crcs)} local audio "
                f"file(s) match by CRC — not a full match")

    if len(full_matches) == 1:
        log(f"  AUDIO CRC MATCH: {full_matches[0]} "
            f"(unique full content match among {len(candidates)} candidate(s))")
        return full_matches[0]
    if len(full_matches) > 1:
        log(f"  Stage 1b — {len(full_matches)} candidates ALL fully match the "
            f"local audio (byte-identical releases?) — cannot pick one safely")
    else:
        log(f"  Stage 1b — no candidate's audio content fully matched")
    return None


# ---------------------------------------------------------------------------
# Stage 2: Fuzzy search (space-tokens from folder name)
# ---------------------------------------------------------------------------

ROMAN_NUMERALS = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x",
                  "xi", "xii", "xiii", "xiv", "xv"}


def _ordinal_tokens(name):
    """
    Extract tokens that distinguish numbered series entries:
    pure numbers (vol6 → 6, no_3 → 3), roman numerals (II, III),
    and alphanumeric combos like vol6 / vol_6 / ep2.
    The release year is excluded since it is validated separately.

    Uses its own raw tokenization because folder_to_tokens drops
    short tokens like "II", "1", "3" which are exactly what we need here.
    """
    year = extract_year(name)
    s = name.replace("_", " ").replace("-", " ").replace(".", " ")
    s = re.sub(r'[()\[\]]', ' ', s)
    ordinals = set()
    for t in s.split():
        tl = t.lower()
        if tl.isdigit():
            if tl != year and len(tl) <= 3:
                ordinals.add(tl)
        elif len(tl) >= 2 and tl in ROMAN_NUMERALS:
            ordinals.add(tl)
        else:
            # split trailing digits off tokens like vol6, ep2, no3
            m = re.match(r'^([a-z]+)(\d{1,3})$', tl)
            if m:
                ordinals.add(m.group(2))
    return ordinals


def validate_match_reason(candidate, folder_name, override_year=None, override_group=None):
    """
    Validates a srrDB candidate against the local folder name.
    Returns None if the candidate is acceptable, otherwise a short
    human-readable rejection reason for the log.
    """
    folder_year  = override_year  or extract_year(folder_name)
    folder_group = override_group or extract_group(folder_name)
    cand_year    = extract_year(candidate)
    cand_group   = extract_group(candidate)

    if folder_year and cand_year and folder_year != cand_year:
        return f"year mismatch: {cand_year} vs {folder_year}"
    if folder_group and cand_group and folder_group.upper() != cand_group.upper():
        # "_INT" marks an internal-only Scene release. Tolerance is
        # ONE-DIRECTIONAL: only when the LOCAL name is missing the
        # suffix that the srrDB candidate actually carries (e.g. local
        # files only ever had "-ftd.mp3", the real srrDB release is
        # "...-FTD_INT" — srrDB is the only record of this release,
        # so trusting it is safe).
        # The reverse is NOT tolerated: if the local folder explicitly
        # declares itself "..._INT" and the candidate found does NOT,
        # that's a real, separate group edition someone deliberately
        # labeled as internal — accepting it as "the same release"
        # would silently relabel a release that isn't actually on
        # srrDB under a different, unrelated release's identity, even
        # if the audio happens to be byte-identical (the group may
        # have reused the same rip for both an internal and a later
        # public release, but that doesn't make them the same catalog
        # entry). Confirmed as a real false-positive by manual review.
        fg, cg = folder_group.upper(), cand_group.upper()
        is_int_variant = (fg + "_INT" == cg)
        if not is_int_variant:
            return f"group mismatch: {cand_group} vs {folder_group}"

    # Numbered series guard: vol6 must never match vol2,
    # Anthology II must never match Anthology, No_3 never No_2.
    folder_ordinals = _ordinal_tokens(folder_name)
    cand_ordinals   = _ordinal_tokens(candidate)
    if folder_ordinals != cand_ordinals:
        return (f"series number mismatch: "
                f"{sorted(cand_ordinals) or '[]'} vs {sorted(folder_ordinals) or '[]'}")

    # Exclude the group tag tokens from the overlap: the group is
    # already validated separately above, and counting it again would
    # inflate similarity between completely different releases that
    # merely share a group (this exact hole caused the historical
    # VA-TV_Hits → Andreas_Martin bad rename).
    group_tokens = set()
    for g in (folder_group, cand_group):
        if g:
            group_tokens.update(t.lower() for t in re.split(r'[_\-]', g) if t)

    folder_tokens = set(
        t.lower() for t in folder_to_tokens(folder_name)
        if not t.isdigit() and t.lower() not in FORMAT_TAGS
        and t.lower() not in group_tokens
    )
    cand_tokens = set(
        t.lower() for t in folder_to_tokens(candidate)
        if not t.isdigit() and t.lower() not in FORMAT_TAGS
        and t.lower() not in group_tokens
    )
    if not folder_tokens:
        # folder_to_tokens drops tokens of length <= 2, so a heavily
        # abbreviated title like "E.L.E." (Busta Rhymes) tokenizes to
        # single letters "e"/"l"/"e" which all get filtered out,
        # leaving nothing to compare — auto-rejecting an otherwise
        # perfectly correct match. Retry once with the length filter
        # relaxed (still excluding pure digits/format tags/group
        # tokens) before giving up entirely.
        raw = re.split(r'[\s_\-.]+', folder_name)
        folder_tokens = set(
            t.lower() for t in raw
            if t and not t.isdigit() and t.lower() not in FORMAT_TAGS
            and t.lower() not in group_tokens
        )
        cand_raw = re.split(r'[\s_\-.]+', candidate)
        cand_tokens = set(
            t.lower() for t in cand_raw
            if t and not t.isdigit() and t.lower() not in FORMAT_TAGS
            and t.lower() not in group_tokens
        )
        if not folder_tokens:
            cand_tokens_lenient = set(
                t.lower() for t in cand_raw
                if t and not t.isdigit() and t.lower() not in FORMAT_TAGS
                and t.lower() not in group_tokens
            )
            if not cand_tokens_lenient:
                # Neither side has any descriptive text left at all
                # (e.g. a title that's purely digits, like Vorzeichen's
                # "1 2 3") — nothing to compare, but year/group/ordinals
                # already matched to get here, which is as much
                # confirmation as this kind of title can ever give.
                return None
            return "no usable tokens in folder name"
    overlap = len(folder_tokens & cand_tokens) / len(folder_tokens)
    if overlap < 0.5:
        return f"token overlap {overlap:.0%} below 50%"
    return None


def validate_match(candidate, folder_name, override_year=None, override_group=None):
    return validate_match_reason(candidate, folder_name,
                                 override_year=override_year,
                                 override_group=override_group) is None


def _srrdb_search_with_validation(query, folder_name, override_year=None, override_group=None):
    results = _srrdb_search_results(query)
    rejected = 0
    for result in results:
        reason = validate_match_reason(result["release"], folder_name,
                                       override_year=override_year,
                                       override_group=override_group)
        if reason is None:
            if rejected:
                log(f"  ({rejected} candidate(s) rejected before this match)")
            return result["release"]
        rejected += 1
        if rejected <= 5:
            log(f"  CANDIDATE REJECTED ({reason}): {result['release']}")
    if rejected > 5:
        log(f"  ... and {rejected - 5} more candidate(s) rejected")
    return None


def stage2_fuzzy_search(folder_name):
    """
    Search srrDB using space-separated tokens from folder name.
    Requires year in folder name to avoid false positives.
    """
    if not extract_year(folder_name):
        log(f"  Stage 2 — skipped (no year in folder name)")
        return None

    STOPWORDS = {'the', 'and', 'of', 'in', 'a', 'an', 'feat', 'ft', 'vs',
                 'with', 'by', 'for'} | FORMAT_TAGS
    tokens = folder_to_tokens(folder_name)
    search_tokens = [t for t in tokens if t.lower() not in STOPWORDS]
    query = " ".join(search_tokens[:8])

    log(f"  Stage 2 — fuzzy search: {query!r}")
    canonical = _srrdb_search_with_validation(query, folder_name)
    if canonical:
        log(f"  FUZZY MATCH: {canonical}")
    return canonical


# ---------------------------------------------------------------------------
# Stage 3: ID3 / NFO fallback
# ---------------------------------------------------------------------------

def _id3_group_from_filename(fname):
    """
    Guesses a group tag from the trailing "-XXXX" segment of a media
    filename. This is only a heuristic — if the local naming has no
    real group suffix at all (just "artist-tracknum-title.mp3" with
    no group), it will happily grab a word from the title instead
    (e.g. "01-nas-freestyle.mp3" -> "FREESTYLE", mistaking the track
    title for a release group). Caller is expected to cross-check
    this against multiple files before trusting it.
    """
    m = re.search(r'--([A-Za-z0-9_]{2,12})\.mp3$', fname, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    m = re.search(r'-([A-Za-z0-9_]{2,12})\.mp3$', fname, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return None


def extract_from_id3(folder):
    """
    Reads album/year/group from tags of the first media file.
    Supports both MP3 (ID3) and FLAC (Vorbis comments) — a release
    with only FLAC files previously got no tag data at all here,
    since only .mp3 was ever considered.

    The group guessed from the trailing filename segment is only
    trusted if it's IDENTICAL across all tracks in the folder. A
    real Scene group suffix is consistent on every track; a random
    trailing word from a differently-worded title (like "freestyle"
    or "friends") won't be, which is exactly how the false positive
    is told apart from a real group tag here.
    """
    media = sorted(f for f in os.listdir(folder)
                   if f.lower().endswith(('.mp3', '.flac')))
    if not media:
        return None, None, None

    first = media[0]
    album = year = group = artist = None

    if first.lower().endswith('.mp3'):
        try:
            from mutagen.id3 import ID3
            tags   = ID3(os.path.join(folder, first))
            album  = str(tags.get('TALB', '')).strip() or None
            artist = str(tags.get('TPE1', '')).strip() or None
            year   = str(tags.get('TDRC', '')).strip()[:4]
            year   = year if re.match(r'^\d{4}$', year) else None
        except Exception:
            pass
    else:
        try:
            from mutagen.flac import FLAC
            tags   = FLAC(os.path.join(folder, first))
            album  = (tags.get('album', [''])[0] or '').strip() or None
            artist = (tags.get('artist', [''])[0] or '').strip() or None
            year   = (tags.get('date', [''])[0] or '').strip()[:4]
            year   = year if re.match(r'^\d{4}$', year) else None
        except Exception:
            pass

    # Only .mp3 filenames carry a plausible trailing group tag in
    # this archive's naming convention; check consistency across
    # every track before trusting it.
    mp3s = [f for f in media if f.lower().endswith('.mp3')]
    if mp3s:
        guesses = {_id3_group_from_filename(f) for f in mp3s}
        if len(guesses) == 1 and None not in guesses:
            group = guesses.pop()

    return album, year, group, artist


def extract_from_nfo(folder):
    nfos = [f for f in os.listdir(folder) if f.lower().endswith('.nfo')]
    if not nfos:
        return None, None
    try:
        with open(os.path.join(folder, nfos[0]), encoding='latin-1') as f:
            content = f.read()
    except Exception:
        return None, None

    year = None
    m = re.search(r'DATE\s+REL[EA]+S[EI]+[Dd][.:\s]+(\d{2}-\d{2}-)?(\d{4})', content, re.IGNORECASE)
    if m:
        year = m.group(2)
        if year == "0000":
            year = None  # common placeholder for "not filled in", not a real year

    # Words that are NFO template field labels, not group names. When
    # a "RIPPER:"/"GROUP:"/"TEAM:" field is left blank, the regex below
    # can otherwise bridge past the empty value and grab the next
    # field's label instead (e.g. "ripper.:            date ripped"
    # capturing "DATE"). Anything matching this denylist is discarded.
    NFO_FIELD_LABELS = {
        "DATE", "LABEL", "ENCODER", "BITRATE", "MODE", "URL", "TRACKS",
        "SOURCE", "RELEASE", "NOTES", "INFO", "TITLE", "ARTIST", "GENRE",
        "QUALITY", "RIPPED", "GRABBED", "WEBSITE", "SIZE", "PLAYTIME",
        "CATALOG", "ENC", "TRACK",
    }

    group = None
    # "RiPPER" is deliberately NOT matched here: in the very common
    # "i n f o" template style this field names the INDIVIDUAL who
    # ripped the release (e.g. "know1", "POP KING"), not the Scene
    # group — trusting it produced wrong group values across a large
    # share of releases. Only "GROUP:"/"TEAM:" are trusted, which are
    # far less ambiguous when they do appear.
    m = re.search(r'(?:GROUP|TEAM)[.:\s]+(?:team\s+)?([A-Za-z0-9_]{2,12})', content, re.IGNORECASE)
    if m:
        candidate = m.group(1).upper()
        if candidate not in NFO_FIELD_LABELS:
            group = candidate

    return year, group


def _stem_fallback_album(folder_path):
    """Same stem extraction technique as Stage 1, used as a fallback
    album text when the ID3 tag itself is unusable."""
    for root, _, files in os.walk(folder_path):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in {".nfo", ".sfv", ".m3u"}:
                stem = _strip_numeric_prefix(os.path.splitext(f)[0])
                return stem.replace("_", " ").replace("-", " ")
    return None


GENERIC_ALBUM_VALUES = {
    "ep", "lp", "cd", "vls", "cds", "cdm", "vinyl", "single", "maxi",
    "mcd", "promo", "tape", "12\"", "7\"", "cdr", "cdep",
}


def _is_generic_album(album):
    """
    True for album tags that are really just a format descriptor
    rather than an actual title — e.g. Souls Of Mischief's TALB tag
    is literally 12" (a ripping error), which produces a single
    near-meaningless token that can never overlap with the real
    candidate title. Anything this short or on the denylist is
    treated as unusable.
    """
    a = album.strip().strip('"').strip().lower()
    return len(a) < 4 or a in GENERIC_ALBUM_VALUES


def stage3_id3_search(folder_path, folder_name):
    """
    Extract metadata from ID3 tags and NFO, build a search query.
    """
    album, id3_year, id3_group, artist = extract_from_id3(folder_path)
    nfo_year, nfo_group = extract_from_nfo(folder_path)

    year  = id3_year  or nfo_year
    group = id3_group or nfo_group or extract_group(folder_name)

    if album and _is_generic_album(album):
        fallback = _stem_fallback_album(folder_path)
        if fallback:
            log(f"  Stage 3 — album tag {album!r} is non-descriptive, "
                f"using filename stem instead: {fallback!r}")
            album = fallback

    if not album:
        log(f"  Stage 3 — no album tag found, skipping")
        return None

    album_tokens = [t for t in re.split(r'[\s_\-]+', album)
                    if t.lower() not in FORMAT_TAGS and len(t) > 1]
    # Artist tokens go first in the query too, not just in the
    # validation compare_text: a bare short album title like "E.L.E."
    # can be too weak a query on its own for srrDB's search API to
    # return the right results — confirmed by hand: searching just
    # the album/year/group came back empty, while adding the artist
    # name to the query found the release immediately.
    artist_tokens = [t for t in re.split(r'[\s_\-]+', artist)
                     if t.lower() not in FORMAT_TAGS and len(t) > 1] if artist else []
    query_parts = artist_tokens[:4] + album_tokens[:6]
    if year:
        query_parts.append(year)
    if group:
        query_parts.append(group)

    if len(query_parts) < 2:
        return None

    query = " ".join(query_parts)
    log(f"  Stage 3 — ID3/NFO search: {query!r} (year={year}, group={group})")
    # Validate candidates against the ALBUM text, not the raw on-disk
    # folder name. When releases arrive via generic downloaders (Usenet
    # nzb clients etc.) the folder is often a meaningless hash like
    # "nzb_2ae9746117fc51b0481984c50e74e5bd" — comparing token overlap
    # or series numbers against that garbage text made every candidate
    # score 0% overlap and get rejected, even for an obviously correct
    # match. year/group are already validated separately via the
    # override_year/override_group below, so this only affects the
    # title/series comparison, which artist+album actually describes.
    # The artist name matters here too: a candidate release name always
    # includes the artist, but an all-digit or single-word album title
    # (e.g. Vorzeichen's "1 2 3") leaves nothing else to compare against
    # once format tags and pure numbers are filtered out.
    compare_text = f"{artist} {album}" if artist else album
    if not compare_text:
        compare_text = folder_name
    canonical = _srrdb_search_with_validation(
        query, compare_text, override_year=year, override_group=group
    )
    if canonical:
        log(f"  ID3 MATCH: {canonical}")
    return canonical


# ---------------------------------------------------------------------------
# srrDB details + SRR helpers
# ---------------------------------------------------------------------------

def srrdb_details_from_srr(canonical_name, folder):
    srr_path = os.path.join(folder, canonical_name + ".srr")
    url = f"https://www.srrdb.com/download/srr/{requests.utils.quote(canonical_name)}"
    try:
        r = _srrdb_request(url, timeout=30)
        if r is None or r.status_code != 200 or len(r.content) < 100:
            log(f"  DETAILS_FROM_SRR: download failed (HTTP {r.status_code if r else 'n/a'})")
            return None
        with open(srr_path, "wb") as f:
            f.write(r.content)
        stats["srr_downloads"] += 1
        log(f"  DETAILS_FROM_SRR: downloaded {len(r.content)} bytes")
    except ApiBlockedError:
        raise
    except Exception as e:
        log(f"  DETAILS_FROM_SRR download error: {e}")
        return None

    try:
        result = subprocess.run(
            [sys.executable, SRR_PY, "-l", os.path.basename(srr_path)],
            cwd=folder, capture_output=True, text=True
        )
        if result.returncode != 0:
            log(f"  DETAILS_FROM_SRR: srr.py -l failed (exit code {result.returncode})")
            for line in (result.stderr or "").strip().splitlines():
                log(f"    STDERR: {line}")
        files = []
        for line in result.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 3:
                try:
                    crc_part = parts[-1].upper()
                    if len(crc_part) == 8:
                        files.append({
                            "name": parts[0],
                            "size": int(parts[-2]),
                            "crc":  crc_part,
                        })
                except (ValueError, IndexError):
                    pass
        if files:
            log(f"  DETAILS_FROM_SRR: found {len(files)} file(s)")
            return {"name": canonical_name, "files": files, "archived-files": [], "adds": []}
        return None
    except Exception as e:
        log(f"  DETAILS_FROM_SRR listing error: {e}")
        return None


def srrdb_details(canonical_name, folder=None):
    try:
        r = _srrdb_request(
            f"https://api.srrdb.com/v1/details/{requests.utils.quote(canonical_name)}"
        )
        if r is None:
            return None
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and data.get("name"):
                return data
            # srrDB bug: empty list instead of 404
            if isinstance(data, list) and folder:
                log(f"  DETAILS LIST(0) — falling back to SRR")
                return srrdb_details_from_srr(canonical_name, folder)
        if r.status_code == 404 and folder:
            log(f"  DETAILS 404 — falling back to SRR")
            return srrdb_details_from_srr(canonical_name, folder)
        return None
    except ApiBlockedError:
        raise
    except Exception as e:
        log(f"  DETAILS ERROR: {e}")
    return None


def download_srr(canonical_name, folder):
    target = os.path.join(folder, canonical_name + ".srr")
    if os.path.isfile(target) and os.path.getsize(target) >= 100:
        log(f"  SRR REUSE: {canonical_name}.srr")
        return target
    url = f"https://www.srrdb.com/download/srr/{requests.utils.quote(canonical_name)}"
    log(f"  SRR DOWNLOAD: {canonical_name}")
    if DRY_RUN:
        log(f"  [DRY] would download {url}")
        stats["srr_downloads"] += 1
        return target
    try:
        r = _srrdb_request(url, timeout=30)
        if r is None or r.status_code != 200:
            log(f"  SRR DOWNLOAD failed (HTTP {r.status_code if r else 'n/a'})")
            return None
        with open(target, "wb") as f:
            f.write(r.content)
        size = os.path.getsize(target)
        if size < 100:
            log(f"  SRR too small ({size} bytes)")
            return None
        stats["srr_downloads"] += 1
        log(f"  SRR OK: {size} bytes (total: {stats['srr_downloads']})")
        return target
    except ApiBlockedError:
        raise
    except Exception as e:
        log(f"  SRR DOWNLOAD ERROR: {e}")
        return None


def extract_srr(folder, srr_path):
    """
    Extracts the metadata files (nfo/m3u/sfv/...) stored inside the SRR
    back onto disk via srr.py -x -y, overwriting whatever's already
    there. Returns True if the subprocess actually ran and exited 0,
    False otherwise — the caller uses this to tell "extraction really
    happened" apart from "extraction silently did nothing", which
    check_metadata_crcs() alone can't distinguish (both look identical
    to it: the files on disk are simply still wrong).

    v2.28: previously only result.stdout was logged, and the return
    code was never checked at all. Confirmed via a real case
    (Nas-It_Aint_Hard_To_Tell_(Pj-Edit)-2003-DGN) that this subprocess
    can fail completely silently: the metadata files on disk were
    legitimately CRC-mismatched (confirmed correct against srrDB's own
    stored CRCs), the SRR downloaded fine, "SRR EXTRACT:" logged with
    zero output lines after it, and the re-check right after showed the
    EXACT SAME mismatches as before extraction — meaning srr.py never
    touched the files at all, and nothing in the log said why. srr.py
    is historically a Python 2 script; if "python" resolves to Python 3
    in this environment, the subprocess can fail immediately (bad
    interpreter, import error, etc.) with the real reason going only to
    stderr, which this function used to discard entirely. Now logs the
    return code and stderr whenever it's non-zero, and catches
    FileNotFoundError (e.g. "python" not on PATH at all) explicitly
    instead of letting it propagate out and abort the whole run.
    """
    log(f"  SRR EXTRACT:")
    if DRY_RUN:
        log(f"  [DRY] would extract {os.path.basename(srr_path)}")
        return True
    try:
        result = subprocess.run(
            [sys.executable, SRR_PY, "-x", "-y", os.path.basename(srr_path)],
            cwd=folder, capture_output=True, text=True
        )
    except FileNotFoundError as e:
        log(f"    EXTRACT FAILED TO START: {e}")
        return False
    for line in (result.stdout or "").strip().splitlines():
        log(f"    {line}")
    if result.returncode != 0:
        log(f"    EXTRACT FAILED (exit code {result.returncode})")
        for line in (result.stderr or "").strip().splitlines():
            log(f"    STDERR: {line}")
        return False
    return True

# ---------------------------------------------------------------------------
# File utilities
# ---------------------------------------------------------------------------

def compute_crc(path):
    crc = 0
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(65536), b""):
            crc = zlib.crc32(chunk, crc)
    return f"{crc & 0xFFFFFFFF:08X}"


def parse_sfv(path):
    entries = []
    try:
        with open(path, "r", encoding="latin-1") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith(";"):
                    continue
                parts = line.rsplit(" ", 1)
                if len(parts) != 2:
                    continue
                filename, crc = parts[0].strip(), parts[1].strip().upper()
                if len(crc) != 8 or "." not in filename:
                    continue
                entries.append((filename, crc))
    except Exception as e:
        log(f"  SFV PARSE ERROR {path}: {e}")
    return entries


def rename_case_safe(src, dst):
    """
    Renames src to dst. Case-only renames (same name, different
    letter case) go through a temp name because some filesystems
    treat "foo.mp3" -> "FOO.mp3" as a no-op otherwise.

    The temp step is wrapped so a failure never leaves a stray
    "__rename_tmp__" file behind: if the second rename fails (e.g. a
    CIFS/NFS hiccup), the temp file is rolled back to its original
    name and the failure is logged instead of raising and aborting
    the whole run mid-release.
    """
    if src == dst:
        return src
    log(f"  RENAME: {os.path.basename(src)} -> {os.path.basename(dst)}")
    if DRY_RUN:
        return dst
    # On Linux os.rename moves src INTO dst if dst already exists as a directory.
    # Guard against this by checking upfront.
    if os.path.isdir(dst) and src.lower() != dst.lower():
        log(f"  RENAME SKIPPED: target directory already exists: {dst}")
        return src
    if src.lower() == dst.lower():
        # Case-only rename: use temp name to avoid collision
        tmp = src + "__rename_tmp__"
        try:
            os.rename(src, tmp)
        except OSError as e:
            log(f"  RENAME FAILED (step 1/2, nothing changed): {e}")
            return src
        try:
            os.rename(tmp, dst)
        except OSError as e:
            log(f"  RENAME FAILED (step 2/2): {e}")
            # Roll back so the file is never left stuck as *__rename_tmp__
            try:
                os.rename(tmp, src)
                log(f"  RENAME ROLLED BACK: {os.path.basename(tmp)} -> {os.path.basename(src)}")
            except OSError as e2:
                log(f"  RENAME ROLLBACK FAILED — file left as: {tmp}  ({e2})")
            return src
    else:
        try:
            os.rename(src, dst)
        except OSError as e:
            log(f"  RENAME FAILED: {e}")
            return src
    return dst


def normalize_metadata_case(folder, srrdb_files):
    """
    srrDB release names preserve the Scene group's original letter case
    (e.g. "00-Nas-It_Aint_Hard_To_Tell_(Pj-Edit)-2003-DGN.nfo"), but a
    local metadata file can already sit on disk under a different case
    (confirmed via a real live case: the local .nfo/.m3u were entirely
    lowercase, "00-nas-it_aint_hard_to_tell_(pj-edit)-2003-dgn.nfo",
    while srrDB's canonical name is mixed-case). Reading that file via
    its canonical-cased path still worked fine (this archive sits on a
    CIFS/SMB mount, which resolves lookups/opens case-insensitively),
    which is exactly why check_metadata_crcs() correctly found and
    CRC-checked it as a MISMATCH rather than reporting it MISSING.

    But a plain Linux filesystem call differentiates the two names, and
    when extract_srr() later tries to WRITE the canonically-cased name
    while the differently-cased file still exists, that's effectively a
    second, colliding directory entry from the SMB server's point of
    view, not a same-name overwrite. Confirmed live: srr.py's own
    "open(out_file, 'wb')" raised "PermissionError: [Errno 13]
    Permission denied" for exactly this reason -- extraction looked
    like it silently did nothing (no change before/after), when what
    actually happened is it crashed trying to create a name that
    collided case-insensitively with the existing one.

    Fixes this up front, before the metadata CRC check and before a
    possible SRR extraction: for every metadata file srrDB expects,
    if a local file already exists under a different case, it's
    renamed in place to the exact canonical case via rename_case_safe()
    (which already handles the CIFS case-only-rename quirk via a temp
    name). By the time check_metadata_crcs() or extract_srr() run, the
    on-disk name already matches exactly, so a later extraction is a
    normal same-name overwrite instead of a case-colliding create.
    """
    if DRY_RUN:
        return
    try:
        local_files = {}
        for f in os.listdir(folder):
            if os.path.isfile(os.path.join(folder, f)):
                local_files.setdefault(f.lower(), f)
    except OSError as e:
        log(f"  CASE NORMALIZE: could not list folder ({e})")
        return

    for entry in srrdb_files:
        name = entry.get("name", "")
        ext = os.path.splitext(name)[1].lower()
        if ext not in METADATA_EXTENSIONS:
            continue
        existing = local_files.get(name.lower())
        if existing and existing != name:
            log(f"  CASE MISMATCH (will fix before extract): "
                f"{existing} -> {name}")
            rename_case_safe(os.path.join(folder, existing),
                             os.path.join(folder, name))


def clear_metadata_for_extract(folder, srrdb_files):
    """
    Deletes any locally-existing metadata file that extract_srr() is
    about to recreate from the SRR, right before extraction runs.

    Confirmed via live testing on the Docker host (v2.28/v2.29 diagnostics):
    this archive's share is an Unraid SMB export, mounted into the
    container over CIFS with Unix extensions disabled ("nounix" in the
    mount options, confirmed via "mount | grep archive"). Opening an
    EXISTING file for write on this mount -- srr.py's own
    "open(out_file, 'wb')", and even a plain shell "echo test > file"
    redirect against a brand-new, just-touched test file with no Scene
    history at all -- consistently failed with a flat "Permission
    denied", regardless of the file's letter case (ruling out v2.29's
    case-collision theory as the full story) and regardless of chmod
    (confirmed to have no effect on this mount, again because of
    "nounix" -- the 0755 shown by "ls -la" is a static file_mode mount
    option, not real per-file state). The share's own SMB-level
    permissions for the mount's user are plain Read/Write, confirmed
    live in Unraid's share settings, so this isn't a share-permission
    problem either.
    DELETING that same file, however, was confirmed to work without
    issue in every test. So rather than trying to open-and-overwrite an
    existing metadata file in place (denied outright on this mount),
    each metadata file srrDB is about to re-supply is removed first,
    turning extract_srr()'s write into a plain file CREATE -- confirmed
    clean on this mount in every test so far (a brand-new folder with
    nothing to collide with extracted perfectly). If anything prevents
    the subsequent extraction from actually recreating a given file
    (network hiccup, etc.), check_metadata_crcs() afterwards correctly
    reports it as MISSING rather than MISMATCH -- no worse an outcome
    than today, and clearer in the log about what actually happened.
    """
    if DRY_RUN:
        return
    for entry in srrdb_files:
        name = entry.get("name", "")
        ext = os.path.splitext(name)[1].lower()
        if ext not in METADATA_EXTENSIONS:
            continue
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            try:
                os.remove(path)
                log(f"  CLEARED FOR EXTRACT: {name}")
            except OSError as e:
                log(f"  could not clear {name} before extract: {e}")


def build_crc_map(folder, extensions):
    crc_map = {}
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d.lower() not in ("subs", "extras")]
        for f in files:
            if os.path.splitext(f)[1].lower() not in extensions:
                continue
            full = os.path.join(root, f)
            try:
                crc = compute_crc(full)
                if crc not in crc_map:
                    crc_map[crc] = os.path.relpath(full, folder)
            except OSError:
                pass
    return crc_map


def rename_media_by_crc(folder, sfv_path):
    """
    Renames media files to their canonical SFV names based on CRC matching.
    Returns (renamed_count, missing_list, crc_cache) where crc_cache maps
    relative path → verified CRC so crc_check can skip recomputing them.
    """
    entries    = parse_sfv(sfv_path)
    if not entries:
        return 0, [], {}
    extensions = {os.path.splitext(fn)[1].lower() for fn, _ in entries}
    crc_map    = build_crc_map(folder, extensions)
    log(f"  MEDIA: indexed {len(crc_map)} local file(s), {len(entries)} expected")
    renamed, missing = 0, []
    crc_cache = {}

    for canonical, expected_crc in entries:
        rel = canonical.replace("\\", "/")
        dst = os.path.join(folder, rel)

        if os.path.isfile(dst):
            try:
                actual = compute_crc(dst)
            except OSError:
                missing.append(rel)
                continue
            crc_cache[rel] = actual
            if actual == expected_crc:
                # fix case-only mismatch (common on case-insensitive
                # mounts like CIFS/SMB, where the file already exists
                # under the right name but wrong letter case)
                dir_files = {f.lower(): f for f in os.listdir(os.path.dirname(dst) or folder)}
                real_name = dir_files.get(os.path.basename(dst).lower(), os.path.basename(dst))
                if real_name != os.path.basename(dst):
                    result = rename_case_safe(os.path.join(os.path.dirname(dst) or folder, real_name), dst)
                    if result == dst:
                        renamed += 1
                    else:
                        # rename_case_safe already logged and rolled back
                        missing.append(rel)
                else:
                    log(f"  OK: {rel}")
                continue
            missing.append(rel)
            continue

        if expected_crc in crc_map:
            old_rel = crc_map[expected_crc]
            src = os.path.join(folder, old_rel)
            log(f"  RENAME: {old_rel} → {rel}")
            if not DRY_RUN:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                rename_ok = True
                if src.lower() == dst.lower() and src != dst:
                    tmp = src + "__crc_tmp__"
                    try:
                        os.rename(src, tmp)
                        os.rename(tmp, dst)
                    except OSError as e:
                        log(f"  RENAME FAILED: {old_rel} → {rel}  ({e})")
                        # Roll back to the original name if the tmp file
                        # still exists, so nothing is left stuck mid-rename.
                        if os.path.exists(tmp) and not os.path.exists(src):
                            try:
                                os.rename(tmp, src)
                                log(f"  RENAME ROLLED BACK: {os.path.basename(tmp)} -> {os.path.basename(src)}")
                            except OSError as e2:
                                log(f"  RENAME ROLLBACK FAILED — file left as: {tmp}  ({e2})")
                        rename_ok = False
                else:
                    try:
                        os.rename(src, dst)
                    except OSError as e:
                        log(f"  RENAME FAILED: {old_rel} → {rel}  ({e})")
                        rename_ok = False
                if rename_ok:
                    crc_map[expected_crc] = rel
                    # CRC was verified when building crc_map
                    crc_cache[rel] = expected_crc
                else:
                    missing.append(rel)
                    continue
            renamed += 1
            continue

        log(f"  MISSING: {rel}")
        missing.append(rel)

    log(f"  RENAME SUMMARY: {renamed} renamed, {len(missing)} missing/failed")
    return renamed, missing, crc_cache


def crc_check(folder, sfv_path, crc_cache=None):
    """
    Verifies all files listed in the SFV. If crc_cache is provided
    (from rename_media_by_crc), cached CRCs are reused instead of
    re-reading files, halving disk I/O on large releases.
    """
    entries  = parse_sfv(sfv_path)
    success  = True
    failures = []
    crc_cache = crc_cache or {}
    for filename, expected_crc in entries:
        rel  = filename.replace("\\", "/")
        path = os.path.join(folder, rel)
        if not os.path.isfile(path):
            log(f"  MISSING: {rel}")
            success = False
            failures.append(f"MISSING:{rel}")
            continue
        if rel in crc_cache:
            actual = crc_cache[rel]
        else:
            try:
                actual = compute_crc(path)
            except OSError as e:
                log(f"  CANNOT READ: {rel}: {e}")
                success = False
                failures.append(f"MISSING:{rel}")
                continue
        if actual == expected_crc:
            log(f"  OK: {rel}")
        else:
            log(f"  FAIL: {rel} (expected {expected_crc}, got {actual})")
            success = False
            failures.append(f"CRC_FAIL:{rel}")
    return success, failures


def _normalize_stem(s):
    """Lowercase, strip a trailing .sfv extension (if present), strip
    numeric prefix and any non-alphanumeric chars, so filenames that
    only differ by case/punctuation/prefix compare as identical.
    Does NOT use os.path.splitext, since dotted release names (movie-
    style naming like "2.Days.in.The.Valley.1996...") would otherwise
    get truncated at the last dot as if it were a file extension."""
    if s.lower().endswith(".sfv"):
        s = s[:-4]
    s = _strip_numeric_prefix(s)
    return re.sub(r'[^a-z0-9]', '', s.lower())


def select_sfv_for_canonical(sfv_files, canonical):
    """
    A folder can contain more than one .sfv — most commonly because
    an unrelated release's metadata got bundled into it by mistake,
    alongside a second, SELF-REFERENTIAL .sfv that was generated
    locally from whatever media files actually sit in the folder.
    Blindly using find_sfv()[0] (whichever happens to sort first on
    disk) risks running the final audio CRC check against that
    self-referential file — which was never checked against srrDB at
    all, so a completely unrelated set of local files can "pass" by
    matching only itself, while the metadata that legitimately
    verified against srrDB belonged to a different release entirely.

    This picks the .sfv whose filename actually corresponds to the
    matched canonical release, so the audio check is verified against
    the SAME release the metadata match was for. If the real audio
    content doesn't actually match that release, CRC check now
    correctly fails and the release goes to incomplete for review,
    instead of silently "passing" a meaningless self-check.
    """
    target = _normalize_stem(canonical)
    for path in sfv_files:
        if _normalize_stem(os.path.basename(path)) == target:
            return path
    return sfv_files[0]


def find_sfv(folder):
    result = []
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower().endswith(".sfv"):
                result.append(os.path.join(root, f))
    return result


def local_metadata_types(folder):
    found = set()
    for root, _, files in os.walk(folder):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in METADATA_EXTENSIONS:
                found.add(ext)
    return found


def expected_metadata_types(srrdb_files):
    found = set()
    for f in srrdb_files:
        ext = os.path.splitext(f["name"])[1].lower()
        if ext in METADATA_EXTENSIONS:
            found.add(ext)
    return found


def check_metadata_crcs(folder, srrdb_files, canonical=None):
    """
    Checks every metadata file the SRR declares against what's
    actually on disk. If `canonical` is given, entries whose own
    filename stem is clearly unrelated to this release (a completely
    different artist/title, sharing no meaningful overlap) are
    reported but NOT counted as a blocking mismatch — this happens
    when srrDB's own stored SRR bundles a stray, unrelated file from
    a totally different release (confirmed in practice: an SRR for
    one release contained a second .m3u entry for an entirely
    different, unrelated artist, which extracts as an empty 0-byte
    stub since its real content was never actually part of this
    archive). One foreign leftover shouldn't fail an otherwise fully
    valid release.
    """
    target = _normalize_stem(canonical) if canonical else None
    mismatches = []
    for entry in srrdb_files:
        name = entry.get("name", "")
        ext  = os.path.splitext(name)[1].lower()
        if ext not in METADATA_EXTENSIONS:
            continue
        expected_crc = entry.get("crc", "").upper()
        if not expected_crc or len(expected_crc) != 8:
            continue

        is_foreign = False
        if target:
            entry_norm = _normalize_stem(name)
            # A meaningful overlap check: the entry's own normalized
            # stem should share a real substring relationship with
            # the canonical release name, not just a handful of
            # coincidentally common short words.
            is_foreign = not (entry_norm in target or target in entry_norm)

        local_path = os.path.join(folder, name)
        if not os.path.isfile(local_path):
            if is_foreign:
                log(f"  META CRC FOREIGN (ignored, unrelated to this release): {name}")
                continue
            log(f"  META CRC MISSING: {name}")
            mismatches.append(name)
            continue
        try:
            actual_crc = compute_crc(local_path)
        except OSError:
            if not is_foreign:
                mismatches.append(name)
            continue
        if actual_crc == "00000000":
            if is_foreign:
                log(f"  META CRC FOREIGN (ignored, unrelated to this release): {name}")
                if not DRY_RUN:
                    os.remove(local_path)
                continue
            log(f"  META CRC EMPTY: {name}")
            if not DRY_RUN:
                os.remove(local_path)
            mismatches.append(name)
        elif actual_crc != expected_crc:
            if is_foreign:
                log(f"  META CRC FOREIGN (ignored, unrelated to this release): {name}")
                continue
            log(f"  META CRC MISMATCH: {name} (expected {expected_crc}, got {actual_crc})")
            mismatches.append(name)
        else:
            log(f"  META CRC OK: {name}")
    return mismatches


def cleanup_srs(folder):
    removed = [f for root, _, files in os.walk(folder)
               for f in files if f.lower().endswith(".srs")]
    if removed:
        if not DRY_RUN:
            for root, _, files in os.walk(folder):
                for f in files:
                    if f.lower().endswith(".srs"):
                        os.remove(os.path.join(root, f))
        log(f"  removed {len(removed)} .srs file(s)")


def cleanup_srr(folder):
    removed = [f for root, _, files in os.walk(folder)
               for f in files if f.lower().endswith(".srr")]
    if removed:
        if not DRY_RUN:
            for root, _, files in os.walk(folder):
                for f in files:
                    if f.lower().endswith(".srr"):
                        os.remove(os.path.join(root, f))
        log(f"  removed {len(removed)} .srr file(s)")


def count_media(folder):
    count = 0
    for root, _, files in os.walk(folder):
        for f in files:
            if os.path.splitext(f)[1].lower() in MEDIA_EXTENSIONS:
                count += 1
    return count


TMP_RENAME_SUFFIXES = ("__rename_tmp__", "__crc_tmp__")


def heal_stray_tmp_renames(folder):
    """
    Finds and repairs leftover *__rename_tmp__ / *__crc_tmp__ files from
    a previously interrupted rename (crashed run, a CIFS/NFS mount going
    stale mid-rename, etc.). The content of these files is untouched,
    only the filename got stuck mid-swap, so healing just means
    stripping the suffix back off — but only if that doesn't collide
    with a file that's already using the clean name.

    Runs at the very start of scan_release_folder so a stray tmp file
    from an earlier failure never masquerades as a MISSING file in the
    CRC check that follows.
    """
    healed = 0
    for root, _, files in os.walk(folder):
        for f in files:
            for suffix in TMP_RENAME_SUFFIXES:
                if not f.endswith(suffix):
                    continue
                stuck = os.path.join(root, f)
                clean_name = f[: -len(suffix)]
                clean = os.path.join(root, clean_name)
                if os.path.exists(clean):
                    log(f"  STRAY TMP FILE (target already exists, left as-is): {f}")
                    break
                if DRY_RUN:
                    log(f"  [DRY] would heal stray tmp file: {f} -> {clean_name}")
                    break
                try:
                    os.rename(stuck, clean)
                    log(f"  HEALED STRAY TMP FILE: {f} -> {clean_name}")
                    healed += 1
                except OSError as e:
                    log(f"  HEAL FAILED for {f}: {e}")
                break
    return healed


def scan_release_folder(folder):
    """
    Single os.walk pass collecting everything process_folder needs:
    SFV paths, media file count and metadata stems for Stage 1.
    Replaces three separate directory walks per release.
    """
    heal_stray_tmp_renames(folder)
    sfvs, media_cnt, stems = [], 0, set()
    for root, _, files in os.walk(folder):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext == ".sfv":
                sfvs.append(os.path.join(root, f))
            if ext in MEDIA_EXTENSIONS:
                media_cnt += 1
            if ext in {".nfo", ".sfv", ".m3u"}:
                stems.add(os.path.splitext(f)[0])
    return sfvs, media_cnt, stems


DUPES_DIR = os.path.join(ARCHIVE_ROOT, "dupes")


def _folders_identical(a, b):
    """True if both folders contain the same filenames (no content check)."""
    try:
        return set(os.listdir(a)) == set(os.listdir(b))
    except OSError:
        return False


USENET_JUNK_EXTENSIONS = {".nzb", ".html", ".htm", ".srr"}


def cleanup_usenet_junk(folder):
    """
    Strips leftover .nzb/.html/.htm/.srr files that sometimes come
    bundled in with "unclean" Usenet downloads — these aren't part
    of the actual Scene release and have no business ending up in
    scenereleases/incomplete/dupes/scenereleases_nosrr. Runs right before every
    physical move, regardless of the outcome, via move_release() and
    move_to_dupes() — covers every destination in one place instead
    of needing a call at each of the dozen or so move call sites.

    .srr is included here too: cleanup_srr() already strips .srr
    right before a successful scene move, but only handles that one
    path. A junk .srr bundled in from Usenet on a release that ends
    up incomplete/nomatch/dupes was never touched before — this
    closes that gap. Harmless overlap with cleanup_srr() on the
    scene path since there's nothing left for it to find there by
    the time this runs.
    """
    removed = [f for root, _, files in os.walk(folder)
               for f in files if os.path.splitext(f)[1].lower() in USENET_JUNK_EXTENSIONS]
    if not removed:
        return
    preview = ", ".join(removed[:5]) + ("..." if len(removed) > 5 else "")
    if DRY_RUN:
        log(f"  [DRY] would remove {len(removed)} leftover Usenet file(s): {preview}")
        return
    for root, _, files in os.walk(folder):
        for f in files:
            if os.path.splitext(f)[1].lower() in USENET_JUNK_EXTENSIONS:
                os.remove(os.path.join(root, f))
    log(f"  removed {len(removed)} leftover Usenet file(s) (.nzb/.html/.htm/.srr): {preview}")


def move_to_dupes(folder, release_name, reason):
    """
    Move a duplicate folder to /archive/dupes with a reason.txt.
    If the name already exists there, a counter suffix is appended:
    ReleaseName.1, ReleaseName.2, ...
    """
    cleanup_usenet_junk(folder)
    if not os.path.exists(DUPES_DIR):
        os.makedirs(DUPES_DIR)
    dst = os.path.join(DUPES_DIR, release_name)
    counter = 0
    while os.path.exists(dst):
        counter += 1
        dst = os.path.join(DUPES_DIR, f"{release_name}.{counter}")
    os.rename(folder, dst)
    with open(os.path.join(dst, "_DUPE_REASON.txt"), "w", encoding="utf-8") as fh:
        fh.write(reason + "\n")
    log(f"  DUPE -> {dst}")
    log(f"  DUPE REASON: {reason.splitlines()[0]}")


def ensure_scene_link(release_name, real_dir):
    """
    v3.0: makes sure scenereleases/<release_name> is a RELATIVE symlink to
    <real_dir>/<release_name> (real_dir = scenereleases_srr or
    scenereleases_nosrr). Never touches a real folder or file with that name
    (logged as a warning), replaces a link with a different target, does
    nothing in dry runs and never raises: a failed link must not stop a run,
    sync_scene_links.py can repair it later.
    """
    if DRY_RUN:
        return
    link = os.path.join(SCENE_DIR, release_name)
    target = os.path.join("..", os.path.basename(real_dir), release_name)
    try:
        os.makedirs(SCENE_DIR, exist_ok=True)
        if os.path.islink(link):
            if os.readlink(link) == target:
                return
            os.remove(link)
        elif os.path.lexists(link):
            log(f"  WARNING: scenereleases/{release_name} exists and is not a symlink, "
                f"no link created (run sync_scene_links.py to check)")
            return
        os.symlink(target, link)
        log(f"  LINK scenereleases/{release_name} -> {target}")
    except OSError as e:
        log(f"  WARNING: could not create link for {release_name}: {type(e).__name__}: {e} "
            f"(sync_scene_links.py --apply repairs it)")


def move_release(folder, target_dir, release_name):
    dst = os.path.join(target_dir, release_name)
    clean_target = target_dir in (SRR_DIR, NOSRR_DIR)
    if DRY_RUN:
        log(f"  [DRY] MOVE → {dst}")
        return
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
    # v3.0: for the two clean folders the name must be free in BOTH of them,
    # scenereleases (the links) is the combined view.
    existing = dst
    if not os.path.exists(existing) and clean_target:
        in_union = os.path.join(SCENE_DIR, release_name)
        if os.path.isdir(in_union):
            existing = os.path.realpath(in_union)
    if os.path.exists(existing):
        if _folders_identical(folder, existing):
            reason = (
                f"Duplicate of: {existing}\n"
                f"Files match (same filenames).\n"
                f"Moved to dupes by incoming_processor on "
                f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            move_to_dupes(folder, release_name, reason)
        else:
            reason = (
                f"Conflict with existing: {existing}\n"
                f"Folders differ in content — manual review needed.\n"
                f"Moved to dupes by incoming_processor on "
                f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            move_to_dupes(folder, release_name, reason)
        return
    cleanup_usenet_junk(folder)
    os.rename(folder, dst)
    log(f"  MOVED → {dst}")
    if clean_target:
        ensure_scene_link(release_name, target_dir)


def check_layout():
    """
    v3.0 safety check, run once at the start of a live run: scenereleases
    must contain ONLY symlinks and scenereleases_srr must exist. Otherwise
    the archive still has the old layout (real releases in scenereleases)
    and migrate_to_v3_layout.py has to run first, because moving a
    release into scenereleases_srr while scenereleases still holds real
    folders would mix both layouts. Returns an error text or None.
    """
    if not os.path.isdir(SRR_DIR):
        return (f"{SRR_DIR} does not exist: the archive still has the old layout. "
                f"Run tools/migrate_to_v3_layout.py first (see docs/MIGRATION.md).")
    if os.path.isdir(SCENE_DIR):
        try:
            with os.scandir(SCENE_DIR) as it:
                for entry in it:
                    if entry.name.startswith("_"):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        return (f"{SCENE_DIR} contains a real folder ({entry.name}): "
                                f"scenereleases must hold only symlinks. "
                                f"Run tools/migrate_to_v3_layout.py / sync_scene_links.py first (see docs/MIGRATION.md).")
        except OSError as e:
            return f"cannot read {SCENE_DIR}: {e}"
    return None


# ---------------------------------------------------------------------------
# Scene workflow (runs after a canonical name is found)
# ---------------------------------------------------------------------------

def run_scene_workflow(folder_path, folder_name, canonical):
    """
    Full scene workflow: rename folder, check/fix metadata, SRR if needed,
    CRC check media, move to scenereleases or incomplete.
    Returns: "SCENE", "INCOMPLETE", "DUPE",
    or "DOWNGRADE" (caller should fall through)
    """
    # Dupe authority is the scenereleases folder itself, not the DB:
    # if the canonical release already sits verified in scenereleases,
    # this copy is a dupe. Checked before any SRR download or CRC work.
    existing = os.path.join(SCENE_DIR, canonical)
    if os.path.isdir(existing):
        log(f"  ALREADY IN scenereleases: {canonical} (-> {os.path.realpath(existing)})")

        # Cheap filename-level comparison (no CRC) so the dupe reason
        # documents how this copy relates to the verified original.
        try:
            arriving_files = set(os.listdir(folder_path))
            existing_files = set(os.listdir(existing))
        except OSError:
            arriving_files, existing_files = set(), set()
        only_arriving = sorted(arriving_files - existing_files)
        only_existing = sorted(existing_files - arriving_files)

        common = arriving_files & existing_files
        if not only_arriving and not only_existing and arriving_files:
            compare_note = "File names identical to verified original."
            log(f"  DUPE FILES: identical file names ({len(arriving_files)} files)")
        elif not common and arriving_files and existing_files:
            # Not a single filename in common — almost certainly the
            # same release under a different naming scheme (e.g. an
            # older re-tagged copy), not a partial/broken duplicate.
            compare_note = (
                f"File names use a completely different naming scheme "
                f"than the verified original: none of the {len(arriving_files)} "
                f"file(s) here match any of the {len(existing_files)} "
                f"file(s) in the original by name (content not compared)."
            )
            log(f"  DUPE FILES: no filenames in common "
                f"({len(arriving_files)} here vs {len(existing_files)} in original "
                f"— likely a differently-named copy of the same release)")
            for f_ in only_arriving[:5]:
                log(f"    only in dupe:     {f_}")
            for f_ in only_existing[:5]:
                log(f"    only in original: {f_}")
        else:
            compare_note = (
                f"File names partially differ from verified original: "
                f"{len(common)} file(s) match by name, "
                f"{len(only_arriving)} file(s) only in this dupe, "
                f"{len(only_existing)} file(s) only in the original."
            )
            log(f"  DUPE FILES: partial match — {len(common)} in common, "
                f"{len(only_arriving)} only here, {len(only_existing)} only in original")
            for f_ in only_arriving[:5]:
                log(f"    only in dupe:     {f_}")
            for f_ in only_existing[:5]:
                log(f"    only in original: {f_}")

        reason_lines = [
            f"Already in scenereleases: {existing}",
            "scenereleases folder is authoritative.",
            compare_note,
        ]
        if only_arriving:
            reason_lines.append("Only in this dupe copy:")
            reason_lines += [f"  {f_}" for f_ in only_arriving[:20]]
        if only_existing:
            reason_lines.append("Only in verified original:")
            reason_lines += [f"  {f_}" for f_ in only_existing[:20]]
        reason_lines.append(
            f"Moved to dupes by incoming_processor on "
            f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        reason = "\n".join(reason_lines)

        if DRY_RUN:
            log(f"  [DRY] would move to dupes: {folder_name}")
        else:
            move_to_dupes(folder_path, folder_name, reason)
        record_result(folder_name, "DUPE", canonical,
                      "already in scenereleases; " + compare_note)
        return "DUPE"

    details_data = srrdb_details(canonical, folder_path)
    if not details_data:
        log(f"  DETAILS failed → downgrade")
        return "DOWNGRADE"

    srrdb_files = details_data.get("files", [])

    # Rename folder to canonical
    canonical_path = os.path.join(os.path.dirname(folder_path), canonical)
    if folder_path != canonical_path:
        log(f"  FOLDER RENAME: {folder_name} → {canonical}")
        folder_path = rename_case_safe(folder_path, canonical_path)

    folder  = folder_path
    release = canonical

    # Fix up any local metadata file sitting under the wrong letter case
    # BEFORE checking/extracting anything (see v2.29 below) -- otherwise
    # a later SRR extraction can crash trying to write a canonically-
    # cased name that collides with an existing differently-cased one
    # on a case-insensitive CIFS/SMB mount.
    normalize_metadata_case(folder, srrdb_files)

    # Metadata check
    expected_meta       = expected_metadata_types(srrdb_files)
    local_meta          = local_metadata_types(folder)
    missing_meta        = expected_meta - local_meta
    log(f"  METADATA expected={sorted(expected_meta)} local={sorted(local_meta)}")

    meta_crc_mismatches = [] if missing_meta else check_metadata_crcs(folder, srrdb_files, canonical)
    need_srr            = bool(missing_meta) or bool(meta_crc_mismatches)

    if need_srr:
        reason = f"missing={sorted(missing_meta)}" if missing_meta else f"crc_mismatch={len(meta_crc_mismatches)}"
        log(f"  SRR needed ({reason})")
        srr = download_srr(canonical, folder)
        if srr and not DRY_RUN:
            clear_metadata_for_extract(folder, srrdb_files)
            extracted = extract_srr(folder, srr)
            if not extracted:
                log(f"  WARNING: SRR extraction did not run successfully — "
                    f"metadata re-check below is against UNCHANGED files")
            cleanup_srs(folder)
            local_meta          = local_metadata_types(folder)
            missing_meta        = expected_meta - local_meta
            meta_crc_mismatches = check_metadata_crcs(folder, srrdb_files, canonical)
        elif DRY_RUN:
            log(f"  [DRY] would extract SRR and re-check metadata")
            missing_meta, meta_crc_mismatches = set(), []
    else:
        log(f"  METADATA OK — SRR skipped")

    if missing_meta or meta_crc_mismatches:
        log(f"  → METADATA still bad → incomplete")
        stats["incomplete"] += 1
        record_result(folder_name, "INCOMPLETE", canonical,
                      "metadata still missing or CRC mismatch after SRR")
        move_release(folder, INCOMPLETE_DIR, release)
        return "INCOMPLETE"

    # SFV check
    sfv_files = find_sfv(folder)
    if not sfv_files:
        if DRY_RUN and need_srr:
            log(f"  [DRY] no SFV yet (would be extracted from SRR) — assuming OK")
            log(f"  [DRY] → scenereleases_srr ✓")
            stats["scene"] += 1
            record_result(folder_name, "SCENE_DRY", canonical,
                          "dry run, SRR extraction pending")
            return "SCENE"
        log(f"  SFV NOT FOUND → incomplete")
        stats["incomplete"] += 1
        record_result(folder_name, "INCOMPLETE", canonical, "sfv_not_found")
        move_release(folder, INCOMPLETE_DIR, release)
        return "INCOMPLETE"

    sfv = select_sfv_for_canonical(sfv_files, canonical)
    if len(sfv_files) > 1:
        log(f"  MULTIPLE SFV FOUND ({len(sfv_files)}) — using the one "
            f"matching the canonical release: {os.path.relpath(sfv, folder)}")
    log(f"  SFV: {os.path.relpath(sfv, folder)}")
    _, _, crc_cache = rename_media_by_crc(folder, sfv)
    crc_ok, crc_failures = crc_check(folder, sfv, crc_cache)

    if not crc_ok:
        log(f"  CRC FAILED → incomplete")
        stats["incomplete"] += 1
        record_result(folder_name, "INCOMPLETE", canonical,
                      _failures_detail(crc_failures))
        move_release(folder, INCOMPLETE_DIR, release)
        return "INCOMPLETE"

    cleanup_srr(folder)
    log(f"  → scenereleases_srr ✓")
    stats["scene"] += 1
    record_result(folder_name, "SCENE", canonical,
                  f"all CRCs verified ({len(crc_cache)} file(s))")
    move_release(folder, SRR_DIR, release)
    return "SCENE"

# Collected per-release outcomes of THIS run, printed as a list at the
# end of the summary and written to a parallel results log.
RUN_RESULTS = []

# result label → human-readable destination folder
RESULT_DESTINATIONS = {
    "SCENE":              "scenereleases_srr",
    "SCENE_DRY":          "scenereleases_srr (dry run)",
    "INCOMPLETE":         "incomplete",
    "DUPE":               "dupes",
    "NOMATCH_OK":         "scenereleases_nosrr",
    "NOMATCH_INCOMPLETE": "incomplete",
    "NOSCENE_OK":         "scenereleases_nosrr",
    "NOSCENE_FAIL":       "incomplete",
    "MP3S":               "mp3s",
    "LEFT_ALONE":         "incoming (left in place)",
}


def _failures_detail(failures, cap=5):
    """
    Formats a CRC/missing failure list for DB details and the results
    summary: capped at `cap` entries, with an explicit note on how
    many more were omitted so nothing silently disappears.
    """
    text = "; ".join(failures[:cap])
    if len(failures) > cap:
        text += f"; ... and {len(failures) - cap} more problem(s)"
    return text


def record_result(folder_name, result, canonical="", details=""):
    """Records this run's outcome for the end-of-run summary — no
    persistent storage anymore, purely in-memory for the duration of
    this run (the DB-backed history was removed; dupe detection has
    been folder-based, not DB-based, since long before this)."""
    RUN_RESULTS.append((folder_name, result, canonical, details))


# ---------------------------------------------------------------------------
# Main folder processor
# ---------------------------------------------------------------------------

def process_folder(folder_path, folder_name):
    log(f"\n--- {folder_name}")

    sfv_files, media_cnt, raw_stems = scan_release_folder(folder_path)
    has_sfv    = bool(sfv_files)
    scene_like = has_scene_name(folder_name)

    # ── Stage 0: Exact folder name match against srrDB ───────────────────
    log(f"  Stage 0 — exact folder name search")
    canonical = srrdb_search_exact(folder_name)
    if canonical:
        if canonical.lower() == folder_name.lower():
            log(f"  EXACT FOLDER MATCH: {canonical}")
        else:
            log(f"  EXACT FOLDER MATCH (cased): {folder_name} → {canonical}")
        stats["exact_match"] += 1
        result = run_scene_workflow(folder_path, folder_name, canonical)
        if result != "DOWNGRADE":
            return

    # ── Stage 1: Stem search ──────────────────────────────────────────────
    canonical = stage1_stem_search(folder_path, folder_name, raw_stems=raw_stems)
    if canonical:
        stats["stem_match"] += 1
        result = run_scene_workflow(folder_path, folder_name, canonical)
        if result != "DOWNGRADE":
            return

    # ── Stage 1b: Audio CRC search ────────────────────────────────────────
    if not canonical:
        canonical = stage1b_audio_crc_search(folder_path, folder_name, raw_stems=raw_stems)
        if canonical:
            stats["audio_crc_match"] += 1
            result = run_scene_workflow(folder_path, folder_name, canonical)
            if result != "DOWNGRADE":
                return

    # ── Stage 2: Fuzzy search ─────────────────────────────────────────────
    if not canonical:
        canonical = stage2_fuzzy_search(folder_name)
        if canonical:
            stats["fuzzy_match"] += 1
            result = run_scene_workflow(folder_path, folder_name, canonical)
            if result != "DOWNGRADE":
                return

    # ── Stage 3: ID3/NFO fallback ─────────────────────────────────────────
    if not canonical:
        canonical = stage3_id3_search(folder_path, folder_name)
        if canonical:
            stats["id3_match"] += 1
            result = run_scene_workflow(folder_path, folder_name, canonical)
            if result != "DOWNGRADE":
                return

    # ── No srrDB match ────────────────────────────────────────────────────
    stats["no_match"] += 1

    # Document the routing decision inputs so the log explains
    # WHY this release ends up in scenereleases_nosrr or incomplete.
    log(f"  CLASSIFY: srrdb_match=no, sfv={'yes' if has_sfv else 'no'}, "
        f"scene_name={'yes' if scene_like else 'no'}, media_files={media_cnt}")

    if has_sfv:
        sfv = sfv_files[0]
        log(f"  No srrDB match — SFV check: {os.path.relpath(sfv, folder_path)}")
        _, _, crc_cache = rename_media_by_crc(folder_path, sfv)
        crc_ok, crc_failures = crc_check(folder_path, sfv, crc_cache)

        if scene_like:
            if crc_ok:
                log(f"  → scenereleases_nosrr ✓")
                stats["nomatch_ok"] += 1
                record_result(folder_name, "NOMATCH_OK",
                              details="no srrDB match; local SFV CRC ok; scene-like name")
                move_release(folder_path, NOSRR_DIR, folder_name)
            else:
                log(f"  → incomplete (no srrDB match)")
                stats["nomatch_fail"] += 1
                record_result(folder_name, "NOMATCH_INCOMPLETE",
                              details="no srrDB match; SFV CRC failed; " + _failures_detail(crc_failures))
                move_release(folder_path, NOMATCH_INCOMPLETE_DIR, folder_name)
        else:
            if crc_ok:
                log(f"  → scenereleases_nosrr (not scene-like) ✓")
                stats["noscene_ok"] += 1
                record_result(folder_name, "NOSCENE_OK",
                              details="no srrDB match; SFV CRC ok; name not scene-like")
                move_release(folder_path, NOSRR_DIR, folder_name)
            else:
                log(f"  → incomplete (no srrDB match, not scene-like, CRC failed)")
                stats["noscene_fail"] += 1
                record_result(folder_name, "NOSCENE_FAIL",
                              details="no srrDB match; not scene-like; SFV CRC failed; " + _failures_detail(crc_failures))
                move_release(folder_path, INCOMPLETE_DIR, folder_name)

    elif scene_like:
        log(f"  Scene-like name, no SFV, no srrDB match → left in incoming")
        stats["left_alone"] += 1
        record_result(folder_name, "LEFT_ALONE",
                      details="scene-like name but no SFV and no srrDB match — manual review")

    elif media_cnt > 0:
        log(f"  No SFV, no Scene name, {media_cnt} media file(s) → mp3s")
        stats["mp3s"] += 1
        record_result(folder_name, "MP3S",
                      details=f"no SFV, name not scene-like, {media_cnt} loose media file(s)")
        move_release(folder_path, MP3S_DIR, folder_name)

    else:
        log(f"  Empty folder → left in incoming")
        stats["left_alone"] += 1
        record_result(folder_name, "LEFT_ALONE",
                      details="empty folder, nothing to process")

# ---------------------------------------------------------------------------
# Summary + entry point
# ---------------------------------------------------------------------------

def _group_run_results():
    """
    Groups RUN_RESULTS by DESTINATION FOLDER (so merged categories like
    both incomplete variants or both nomatch variants form one group),
    in a fixed, sensible order: happy path first, review cases last.
    Shared by print_summary() and the Discord report, so both always
    describe a run the exact same way.

    Returns (ordered_keys, grouped) where grouped maps destination name
    to a list of (folder_name, canonical, details) tuples; details is
    blanked for the happy-path SCENE/SCENE_DRY results, which always
    carry the same non-informative "all CRCs verified" message.
    """
    group_order = [
        "scenereleases_srr", "scenereleases_srr (dry run)",
        "scenereleases_nosrr",
        "dupes", "incomplete",
        "mp3s", "incoming (left in place)",
    ]
    no_reason_results = {"SCENE", "SCENE_DRY"}
    grouped = {}
    for folder_name, result, canonical, details in RUN_RESULTS:
        dest = RESULT_DESTINATIONS.get(result, result)
        show_reason = result not in no_reason_results
        grouped.setdefault(dest, []).append(
            (folder_name, canonical, details if show_reason else ""))
    ordered_keys = [k for k in group_order if k in grouped]
    ordered_keys += [k for k in grouped if k not in group_order]
    return ordered_keys, grouped


def print_summary():
    mode = "DRY RUN" if DRY_RUN else "LIVE"
    log(f"\n=====================================")
    log(f"INCOMING PROCESSOR SUMMARY [{mode}]")
    log(f"  Stage 0 exact matches:       {stats['exact_match']}")
    log(f"  Stage 1 stem matches:        {stats['stem_match']}")
    log(f"  Stage 1b audio CRC matches:  {stats['audio_crc_match']}")
    log(f"  Stage 2 fuzzy matches:       {stats['fuzzy_match']}")
    log(f"  Stage 3 ID3/NFO matches:     {stats['id3_match']}")
    log(f"  No srrDB match:              {stats['no_match']}")
    log(f"  → scenereleases_srr:         {stats['scene']}")
    log(f"  → incomplete:                {stats['incomplete']}")
    log(f"  → scenereleases_nosrr (scene-like):     {stats['nomatch_ok']}")
    log(f"  → incomplete (no srrDB, scene-like):    {stats['nomatch_fail']}")
    log(f"  → scenereleases_nosrr (not scene-like): {stats['noscene_ok']}")
    log(f"  → incomplete (no srrDB, not scene-like):{stats['noscene_fail']}")
    log(f"  → mp3s:                      {stats['mp3s']}")
    log(f"  → Left in incoming:          {stats['left_alone']}")
    log(f"  Skipped (already done):      {stats['skipped']}")
    log(f"  SRR downloads:               {stats['srr_downloads']}")
    log(f"  Log: {LOGFILE}")
    log(f"=====================================")

    # Per-release outcome list, grouped by destination so the
    # distribution of a whole run is visible at a glance.
    if RUN_RESULTS:
        ordered_keys, grouped = _group_run_results()

        # scenereleases entries omit the reason (always the same
        # happy-path message); handled above by blanking details.
        output_lines = []
        for dest in ordered_keys:
            entries = sorted(grouped[dest], key=lambda e: e[0].lower())
            output_lines.append("")
            output_lines.append(f"{dest} ({len(entries)}):")
            for folder_name, canonical, details in entries:
                name_part = f"  {folder_name}"
                if canonical and canonical.lower() != folder_name.lower():
                    name_part += f" (as {canonical})"
                if not details:
                    output_lines.append(name_part)
                elif len(details) > 100 and "; " in details:
                    # Long failure lists wrap onto indented lines so a
                    # release with many broken files stays readable.
                    output_lines.append(f"{name_part} //")
                    for part in details.split("; "):
                        output_lines.append(f"      {part}")
                else:
                    output_lines.append(f"{name_part} // {details}")

        log(f"")
        log(f"RELEASE RESULTS ({len(RUN_RESULTS)})")
        log(f"-------------------------------------")
        for line in output_lines:
            log(line)
        log(f"-------------------------------------")
        log(f"  Results file: {RESULTS_FILE}")

        # Parallel, grep-friendly results log with the same grouping
        try:
            with open(RESULTS_FILE, "w", encoding="utf-8") as f:
                f.write(f"# incoming_processor results [{mode}] "
                        f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                for line in output_lines:
                    f.write(line + "\n")
        except OSError as e:
            log(f"  RESULTS FILE ERROR: {e}")


def main():
    lock_fh = open(LOCKFILE, "w")
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("ERROR: Another instance is already running.")
        lock_fh.close()
        sys.exit(1)
    lock_fh.write(str(os.getpid()))
    lock_fh.flush()
    try:
        _run()
    finally:
        fcntl.flock(lock_fh, fcntl.LOCK_UN)
        lock_fh.close()
        try:
            os.remove(LOCKFILE)
        except OSError:
            pass


def _run():
    mode = "DRY RUN" if DRY_RUN else "LIVE"
    log(f"INCOMING PROCESSOR v{SCRIPT_VERSION} [{mode}]")
    log(f"incoming:     {INCOMING_DIR}")
    log(f"Archive root: {ARCHIVE_ROOT}")
    log("Layout:       scenereleases_srr + scenereleases_nosrr (real), scenereleases (symlinks)")
    if VPN_PROXY_URL:
        log(f"VPN proxy:    {VPN_PROXY_URL} (used only after a block code, real IP first)")
    else:
        log("VPN proxy:    not configured (set VPN_PROXY_URL to enable auto-switch on a block code)")
    log("")

    if not os.path.isdir(INCOMING_DIR):
        log(f"ERROR: incoming directory not found: {INCOMING_DIR}")
        sys.exit(1)

    layout_error = check_layout()
    if layout_error:
        log(f"ERROR: {layout_error}")
        sys.exit(1)

    entries = sorted([
        e for e in os.listdir(INCOMING_DIR)
        if os.path.isdir(os.path.join(INCOMING_DIR, e))
    ])

    log(f"Folders to process: {len(entries)}")
    log("")

    # Track incomplete releases that need to be moved to Replaced after processing
    _incomplete_to_replace = {}

    for i, folder_name in enumerate(entries, 1):
        if _shutdown:
            log("\n!!! Shutdown requested — stopping.")
            break

        folder_path = os.path.join(INCOMING_DIR, folder_name)
        if not os.path.isdir(folder_path):
            continue

        # The DB is history only — it never decides dupes anymore.
        # The scenereleases folder is the authority (checked inside
        # run_scene_workflow once the canonical name is known).
        # If an older copy of this folder still sits in incomplete,
        # remember it so it can be moved to Replaced on success.
        incomplete_path = os.path.join(INCOMPLETE_DIR, folder_name)
        if os.path.isdir(incomplete_path):
            log(f"  Found in incomplete — old copy becomes a Dupe if this one completes")
            _incomplete_to_replace[folder_name] = incomplete_path

        log(f"\n[{i}/{len(entries)}]")
        try:
            process_folder(folder_path, folder_name)
        except ApiBlockedError as e:
            log(f"\n!!! API BLOCKED: {e}")
            log("!!! Stopping. Wait and retry later.")
            print_summary()
            sys.exit(1)
        except Exception as e:
            import traceback
            log(f"  UNHANDLED ERROR: {type(e).__name__}: {e}")
            log(traceback.format_exc())

        time.sleep(REQUEST_DELAY)

    # Superseded incomplete versions become dupes: an old broken copy
    # that was replaced by a newly completed one is just a dupe of a
    # better version. The _DUPE_REASON.txt documents the supersession.
    if _incomplete_to_replace:
        log(f"\nMoving {len(_incomplete_to_replace)} superseded incomplete(s) to dupes...")
        for fname, ipath in _incomplete_to_replace.items():
            scene_path = os.path.join(SCENE_DIR, fname)
            if os.path.isdir(scene_path):
                if not DRY_RUN and os.path.isdir(ipath):
                    reason = (
                        f"Superseded incomplete version.\n"
                        f"A newly completed copy was verified and moved to: {scene_path}\n"
                        f"Moved to dupes by incoming_processor on "
                        f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    move_to_dupes(ipath, fname, reason)
                    log(f"  SUPERSEDED: {fname} → dupes/")
                else:
                    log(f"  [DRY] would move superseded version to dupes: {fname}")
            else:
                log(f"  NOT SUPERSEDED (still incomplete or no scene match): {fname}")

    print_summary()
    trigger_archivedb_reindex()
    post_discord_report()


ARCHIVEDB_URL = os.environ.get("ARCHIVEDB_URL", "")  # e.g. "http://archivedb:8000"


def trigger_archivedb_reindex():
    """
    Optional: pokes the archivedb web browser's /reindex endpoint so
    it picks up whatever this run just changed in scenereleases/,
    without waiting for a manual reindex. Disabled unless ARCHIVEDB_URL
    is set (e.g. via docker-compose environment), and any failure here
    is just logged, never fatal — the archive itself is unaffected
    either way, this only refreshes a separate search index.
    """
    if not ARCHIVEDB_URL:
        return
    try:
        r = requests.post(f"{ARCHIVEDB_URL.rstrip('/')}/reindex", timeout=120)
        if r.status_code == 200 and r.json().get("ok"):
            log("\nArchiveDB reindex triggered successfully.")
        else:
            log(f"\nArchiveDB reindex returned an error: {r.text[:200]}")
    except Exception as e:
        log(f"\nArchiveDB reindex could not be triggered ({e}) — "
            f"run it manually if needed.")


# ---------------------------------------------------------------------------
# Discord report (v2.22)
# ---------------------------------------------------------------------------

DISCORD_WEBHOOK_URL   = os.environ.get("DISCORD_WEBHOOK_URL", "")  # e.g. a
                        # "https://discord.com/api/webhooks/..." URL —
                        # Discord server → channel settings → Integrations
                        # → Webhooks → New Webhook → Copy URL. Disabled
                        # (nothing posted) while this is empty. Deliberately
                        # NOT hardcoded here — keep the real webhook URL out
                        # of the script file itself; set it via the
                        # DISCORD_WEBHOOK_URL environment variable instead
                        # (Unraid: Docker tab → rescene-worker → Edit → Add
                        # another Variable).
DISCORD_SKIP_EMPTY_RUNS = _env_flag("DISCORD_SKIP_EMPTY_RUNS", True)  # ← don't post to Discord when there was
                                 #   nothing in incoming/ to process (e.g.
                                 #   an hourly cron run that found 0
                                 #   folders) — set False to get a ping
                                 #   on every single run regardless.

# Small, readable icon per destination — used both for the field title
# and to make the report scannable at a glance on a phone screen.
_DISCORD_DEST_EMOJI = {
    "scenereleases_srr":            "✅",
    "scenereleases_srr (dry run)":  "✅",
    "dupes":                    "📦",
    "incomplete":               "⚠️",
    "scenereleases_nosrr":      "❓",
    "mp3s":                     "🎵",
    "incoming (left in place)": "⏸️",
}

# Destinations that mean "this run needs a human to look at something",
# used only to pick the embed's color (green = fully clean run).
_DISCORD_ATTENTION_DESTS = {
    "incomplete", "incoming (left in place)",
}

DISCORD_COLOR_OK        = 0x2ECC71  # green  — clean run, nothing to review
DISCORD_COLOR_ATTENTION = 0xE67E22  # orange — something needs a look
DISCORD_EMBED_FIELD_CAP = 15        # max lines listed per destination
                                     # before switching to "... and N more"
DISCORD_EMBED_TOTAL_CAP = 5800      # v2.32: Discord's real hard limit for a
                                     # whole embed (title + every field's
                                     # name+value + footer, all added
                                     # together) is 6000 chars -- each field's
                                     # VALUE already stays under 1024 on its
                                     # own, but a run with many destinations
                                     # can still add those up past 6000. Kept
                                     # a bit below the real limit as a safety
                                     # margin rather than cutting it exactly.

# Discord markdown special characters that need escaping wherever a
# real release/file name is dropped into plain message content — Scene
# names are FULL of underscores ("Artist_Name-Some_Title-2001-GRP"),
# and Discord treats "_word_" as italic markup. Confirmed live: names
# like "DJ_Premier_And_..." rendered with random mid-name italics and
# swallowed underscores because of exactly this. This is only for text
# we did NOT write ourselves — our own **bold**/-# markup must stay
# unescaped, so this is applied to each dynamic value individually,
# never to a whole pre-built line.
_DISCORD_MARKDOWN_SPECIAL_RE = re.compile(r'([\\_*~`|>])')


def _discord_escape(text):
    return _DISCORD_MARKDOWN_SPECIAL_RE.sub(r'\\\1', text)


def _discord_release_line(folder_name, canonical, details):
    """
    Formats one release for the report: the clean srrDB release name
    once one is known, since the messy original incoming folder name
    (spaces, mixed case, dotted acronyms, ...) adds nothing once it's
    already resolved. Falls back to the folder name when there is no
    resolved name at all (mp3s, scenereleases_nosrr, left-in-incoming).
    """
    line = f"• {_discord_escape(canonical or folder_name)}"
    if details:
        # Keep it to one short line per release — the full reason is
        # already in the run's log file.
        line += f" — {_discord_escape(details.split('; ')[0])}"
    return line


def _discord_field_value(entries):
    """
    Formats one destination's (folder_name, canonical, details) list as
    a Discord field value: one bullet per release, capped at
    DISCORD_EMBED_FIELD_CAP lines (with a "... and N more" line) and at
    Discord's 1024-char field-value limit, so one huge run never breaks
    the whole report.
    """
    lines = [_discord_release_line(*e) for e in entries]
    if len(lines) > DISCORD_EMBED_FIELD_CAP:
        omitted = len(lines) - DISCORD_EMBED_FIELD_CAP
        lines = lines[:DISCORD_EMBED_FIELD_CAP]
        lines.append(f"... and {omitted} more")
    value = "\n".join(lines)
    if len(value) > 1024:
        value = value[:1000].rsplit("\n", 1)[0] + "\n... (truncated)"
    return value


def build_discord_messages():
    """
    Builds the Discord webhook payload for this run: a single colored
    embed (green = clean run, orange = something needs a look — this
    IS the "boxed card" look with the vertical color bar down the left
    edge that a plain message can't reproduce), containing the
    "Ergebnis" overview and one field per non-empty destination with
    the actual release names. No "Wie erkannt" stage-match breakdown —
    dropped per feedback, Ergebnis + the per-destination lists are
    enough.

    Embed fields have a fixed, fairly narrow rendered width regardless
    of screen size, so a long release name can still wrap onto a
    second line — that's an actual Discord embed limitation, not
    something this script can configure around, and is accepted as a
    tradeoff for getting the colored box back.
    """
    mode = "DRY RUN" if DRY_RUN else "LIVE"
    ordered_keys, grouped = _group_run_results()

    needs_attention = any(k in _DISCORD_ATTENTION_DESTS for k in grouped)
    color = DISCORD_COLOR_ATTENTION if needs_attention else DISCORD_COLOR_OK
    total = len(RUN_RESULTS)

    overview_lines = [f"{_DISCORD_DEST_EMOJI.get(k, '•')} {k:<24} {len(grouped[k])}"
                       for k in ordered_keys]
    overview = "```\n" + "\n".join(overview_lines) + "\n```" if overview_lines else "```\n(nothing processed)\n```"

    title = f"Incoming Processor — {total} release(s) processed [{mode}]"
    footer_text = f"scene-processor · {LOGFILE.rsplit('/', 1)[-1]}"

    fields = [{"name": "Result", "value": overview, "inline": False}]
    # v2.32: track the running total ourselves (title + every field's
    # name+value + footer) against DISCORD_EMBED_TOTAL_CAP, since that is
    # Discord's real limit for the embed AS A WHOLE, separate from (and
    # much easier to exceed than) the 1024-char cap on one field's value.
    running_total = len(title) + len(footer_text) + len(fields[0]["name"]) + len(fields[0]["value"])

    skipped_dests = []
    for dest in ordered_keys:
        entries = sorted(grouped[dest], key=lambda e: e[0].lower())
        emoji = _DISCORD_DEST_EMOJI.get(dest, "•")
        name = f"{emoji} {dest} ({len(entries)})"
        value = _discord_field_value(entries)
        # 24, not 25: always leave room for the "not shown"
        # field below if we end up needing it.
        if len(fields) >= 24 or running_total + len(name) + len(value) > DISCORD_EMBED_TOTAL_CAP:
            skipped_dests.append(dest)
            continue
        fields.append({"name": name, "value": value, "inline": False})
        running_total += len(name) + len(value)

    if skipped_dests:
        note = ("Not shown any more (embed limit reached): " +
                ", ".join(f"{d} ({len(grouped[d])})" for d in skipped_dests) +
                f" — details in log file {LOGFILE.rsplit('/', 1)[-1]}")
        if len(note) > 1024:
            note = note[:1000].rsplit(",", 1)[0] + ", ... — details in log file"
        note_field = {"name": "⚠️ Note", "value": note, "inline": False}
        # Drop already-added fields from the end if needed to make room —
        # better to show fewer full lists than to risk a second HTTP 400.
        while fields and running_total + len(note_field["name"]) + len(note_field["value"]) > DISCORD_EMBED_TOTAL_CAP and len(fields) > 1:
            removed = fields.pop()
            running_total -= len(removed["name"]) + len(removed["value"])
        fields.append(note_field)

    embed = {
        "title": title,
        "color": color,
        "fields": fields,
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "footer": {"text": footer_text},
    }
    return [{"embeds": [embed]}]


def post_discord_report():
    """
    Posts this run's summary to Discord via an incoming webhook, if
    DISCORD_WEBHOOK_URL is configured. Skipped entirely (no request
    made) when nothing was processed and DISCORD_SKIP_EMPTY_RUNS is
    True — an hourly cron run that finds an empty incoming/ has nothing
    worth pinging about. Sent as one or more sequential messages (see
    build_discord_messages). Never raises: a broken/rate-limited
    webhook only gets logged, it can't fail the actual archive run.
    """
    if not DISCORD_WEBHOOK_URL:
        return
    if not RUN_RESULTS and DISCORD_SKIP_EMPTY_RUNS:
        return
    try:
        payloads = build_discord_messages()
        for i, payload in enumerate(payloads, 1):
            r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
            if r.status_code in (200, 204):
                log(f"\nDiscord report posted successfully ({i}/{len(payloads)}).")
            else:
                log(f"\nDiscord report failed ({i}/{len(payloads)}, "
                    f"HTTP {r.status_code}): {r.text[:300]}")
    except Exception as e:
        log(f"\nDiscord report could not be posted ({e}).")


if __name__ == "__main__":
    main()