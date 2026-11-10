import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.39.3";

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
};

serve(async (req) => {
  if (req.method === 'OPTIONS') {
    return new Response(null, { headers: corsHeaders });
  }

  let pageId: string | undefined;
  
  try {
    const authHeader = req.headers.get('Authorization');
    if (!authHeader) {
      return new Response(
        JSON.stringify({ error: 'Authentication required' }),
        { status: 401, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    const supabaseClient = createClient(
      Deno.env.get('SUPABASE_URL') ?? '',
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? ''
    );
    const accessToken = authHeader.replace(/^Bearer\s+/i, '');
    const { data: { user }, error: authError } = await supabaseClient.auth.getUser(accessToken);
    if (authError || !user) {
      return new Response(
        JSON.stringify({ error: 'Invalid or expired session' }),
        { status: 401, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    const body = await req.json();
    pageId = body.pageId;
    console.log('Translating page:', pageId);

    // Get page details
    const { data: page, error: pageError } = await supabaseClient
      .from('pages')
      .select('*, books(*)')
      .eq('id', pageId)
      .single();

    if (pageError) throw pageError;

    const book = page.books;
    if (!book || book.user_id !== user.id) {
      return new Response(
        JSON.stringify({ error: 'Page not found' }),
        { status: 404, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    // Update page status to processing
    await supabaseClient
      .from('pages')
      .update({ status: 'processing' })
      .eq('id', pageId);

    const userId = book.user_id;
    
    // Get daily translation counts from profile
    const { data: profile } = await supabaseClient
      .from('profiles')
      .select('daily_translations_count, last_translation_date')
      .eq('id', userId)
      .single();
    
    // Check daily translation limit
    const today = new Date().toISOString().split('T')[0];
    const lastTranslationDate = profile?.last_translation_date 
      ? new Date(profile.last_translation_date).toISOString().split('T')[0]
      : null;
    
    let dailyCount = profile?.daily_translations_count || 0;
    
    // Reset counter if it's a new day
    if (lastTranslationDate !== today) {
      dailyCount = 0;
    }
    
    // Get translation settings
    const { data: settings } = await supabaseClient
      .from('settings')
      .select('*')
      .in('key', ['global_translation_prompt', `${book.original_locale}_translation_prompt`]);

    const globalPrompt = settings?.find(s => s.key === 'global_translation_prompt')?.value || '';
    const langPrompt = settings?.find(s => s.key === `${book.original_locale}_translation_prompt`)?.value || '';

    // Any OpenAI-compatible chat endpoint. Defaults to the Lovable AI gateway;
    // set AI_URL / AI_MODEL / AI_API_KEY to call a provider directly (e.g. Gemini).
    const AI_API_KEY = Deno.env.get('AI_API_KEY') ?? Deno.env.get('LOVABLE_API_KEY');
    if (!AI_API_KEY) throw new Error('AI is not configured');
    const AI_URL = Deno.env.get('AI_URL') ?? 'https://ai.gateway.lovable.dev/v1/chat/completions';
    const AI_MODEL = Deno.env.get('AI_MODEL') ?? 'google/gemini-3.1-flash-lite';

    // Split text into lines but process in batches to reduce API calls
    const textLines = page.original_text.split('\n').filter((line: string) => line.trim().length > 0);
    const BATCH_SIZE = 8;

    console.log(`Processing ${textLines.length} lines in batches of ${BATCH_SIZE}...`);

    // Keep the prompt short: long prompts cost latency on every single request.
    const systemPrompt = `${globalPrompt}\n${langPrompt}
Translate from ${book.original_locale} to ${book.target_locale} literally, word by word, for a language learner.

Rules:
- Split every line into small units of 1-3 source words. Never put a whole clause or line in one unit.
- Article + noun stay one unit ("la technologie" -> "the technology"). Compound verbs stay one unit ("a réussi" -> "has succeeded").
- Prepositions are their own unit ("de" -> "of", "à" -> "to").
- Fixed expressions stay one unit ("pomme de terre" -> "potato").
- Keep the source word order. Cover every source word exactly once; add nothing.

Return ONLY JSON: {"lines":[[{"original":"...","translation":"..."}]]} — one array per input line, same order.`;


    // Resume support: lines are stored positionally (index === source line index),
    // so an overlapping invocation can never duplicate or skip a line.
    const existing = (page.translated_data as any) || null;
    const translatedLines: any[] = Array.isArray(existing?.lines)
      ? existing.lines.slice(0, textLines.length)
      : [];
    const isDone = (i: number) => Array.isArray(translatedLines[i]) && translatedLines[i].length > 0;
    const firstMissing = () => {
      for (let i = 0; i < textLines.length; i++) if (!isDone(i)) return i;
      return textLines.length;
    };
    const doneCount = () => {
      let n = 0;
      for (let i = 0; i < textLines.length; i++) if (isDone(i)) n++;
      return n;
    };
    const buildFullTranslation = () =>
      translatedLines
        .filter(line => Array.isArray(line))
        .map((line: any) => line.map((pair: any) => pair.translation).join(' '))
        .join(' ');
    const startIndex = firstMissing();
    const START_TIME = Date.now();
    const TIME_BUDGET_MS = 42000; // leave time to persist and return cleanly
    let partial = false;

    if (startIndex > 0) {
      console.log(`Resuming from line ${startIndex}/${textLines.length}`);
    }


    // Batches run in parallel; this many AI requests at a time.
    const CONCURRENCY = 4;


    // Split a single long line into smaller sentence-ish chunks (recovery path)
    const splitLine = (line: string): string[] => {
      const parts = line
        .split(/(?<=[.!?…»:;])\s+/)
        .map(p => p.trim())
        .filter(p => p.length > 0);
      if (parts.length > 1) return parts;
      // No punctuation: split by word count
      const words = line.trim().split(/\s+/);
      if (words.length < 8) return [line];
      const mid = Math.ceil(words.length / 2);
      return [words.slice(0, mid).join(' '), words.slice(mid).join(' ')];
    };

    // Normalized tokens used to check that the alignment covers exactly the source line
    const tokenize = (text: string): string[] =>
      text
        .toLowerCase()
        .replace(/[«»“”"()\[\]{}.,;:!?…—–\-]/g, ' ')
        .replace(/[’´`]/g, "'")
        .split(/\s+/)
        .filter(t => t.length > 0);

    // Drops pairs the model hallucinated beyond the source line (the cause of the
    // "repeated text" overlap) and reports when the tail of the line is missing.
    const repairLine = (source: string, pairs: any[]): { pairs: any[]; missing: boolean } => {
      const src = tokenize(source);
      const out: any[] = [];
      let idx = 0;
      for (const pair of pairs) {
        const tok = tokenize(String(pair?.original ?? ''));
        if (tok.length === 0) continue;
        let matchAt = -1;
        for (let start = idx; start <= Math.min(src.length - tok.length, idx + 4); start++) {
          if (tok.every((t, k) => src[start + k] === t)) { matchAt = start; break; }
        }
        if (matchAt === -1) continue; // not part of the remaining source: hallucinated / duplicated
        out.push(pair);
        idx = matchAt + tok.length;
      }
      return { pairs: out, missing: idx < src.length };
    };

    const validateLine = (source: string, pairs: any): string | null => {
      if (!Array.isArray(pairs) || pairs.length === 0) return 'empty alignment';
      const sourceWordCount = source.trim().split(/\s+/).length;
      const bad = pairs.some((pair: any) =>
        typeof pair?.original !== 'string' ||
        typeof pair?.translation !== 'string' ||
        pair.original.trim().split(/\s+/).length > 4
      );
      const minimumPairCount = Math.max(1, Math.ceil(sourceWordCount / 4));
      if (bad || pairs.length < minimumPairCount) return 'sentence-level alignment';
      const { missing } = repairLine(source, pairs);
      if (missing) return 'incomplete coverage of the source line';
      return null;
    };


    // Global limiter: recursive splitting must never fan out into many parallel
    // AI calls, otherwise the provider answers 429 for everything.
    let inflight = 0;
    const waiters: (() => void)[] = [];
    const MAX_INFLIGHT = CONCURRENCY;
    const acquire = async () => {
      if (inflight < MAX_INFLIGHT) { inflight++; return; }
      await new Promise<void>(resolve => waiters.push(resolve));
      inflight++;
    };
    const release = () => {
      inflight--;
      const next = waiters.shift();
      if (next) next();
    };

    class RateLimitError extends Error {}
    const isRateLimit = (e: unknown) => e instanceof RateLimitError;
    const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

    const translateBatch = async (batch: string[], label: string): Promise<any[]> => {
      let lastError: Error | null = null;
      // Best structurally-valid result seen (right line count) even if the
      // granularity check failed — used as a last resort so a stubborn line
      // can never deadlock the whole page.
      let bestEffort: any[] | null = null;
      const MAX_ATTEMPTS = 2;

      for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {

        try {
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 22000);

          let response: Response;
          await acquire();
          try {
            response = await fetch(AI_URL, {
              method: 'POST',
              signal: controller.signal,
              headers: {
                'Authorization': `Bearer ${AI_API_KEY}`,
                'Content-Type': 'application/json',
              },
              body: JSON.stringify({
                model: AI_MODEL,
                messages: [
                  { role: 'system', content: systemPrompt },
                  { role: 'user', content: `Translate exactly ${batch.length} numbered line(s). "lines" MUST have exactly ${batch.length} element(s), in the same order — never split one input line into several output lines, even if it contains several sentences. Split every line into small word/phrase units before translating; never return a whole line as one pair.\n\n${batch.map((l, i) => `[${i + 1}] ${l}`).join('\n')}` }
                ],
                response_format: { type: 'json_object' }
              }),
            });

          } finally {
            clearTimeout(timeoutId);
            release();
          }

          if (!response.ok) {
            const errorText = await response.text();
            console.error('AI API error:', response.status, errorText);
            if (response.status === 429) {
              const retryAfter = Number(response.headers.get('retry-after')) || 0;
              const err = new RateLimitError('Rate limit exceeded. Please try again later.');
              (err as any).retryAfterMs = retryAfter > 0 ? retryAfter * 1000 : 0;
              throw err;
            }
            if (response.status === 402) throw new Error('AI credits exhausted. Please add credits to your workspace.');
            throw new Error(`AI API error: ${response.status}`);
          }

          const data = await response.json();
          const result = JSON.parse(data.choices[0].message.content);

          if (!result.lines || !Array.isArray(result.lines)) {
            throw new Error(`AI returned invalid structure for ${label}`);
          }

          let lines = result.lines as any[];

          // Strip any numbering the model copied from the prompt
          for (const l of lines) {
            if (Array.isArray(l)) {
              for (const pair of l) {
                if (typeof pair?.original === 'string') pair.original = pair.original.replace(/^\s*\[\d+\]\s*/, '');
                if (typeof pair?.translation === 'string') pair.translation = pair.translation.replace(/^\s*\[\d+\]\s*/, '');
              }
            }
          }

          // Tolerate the model over-splitting a single input line into several output lines
          if (batch.length === 1 && lines.length > 1) {
            const flat = lines
              .flat(3)
              .filter((p: any) => typeof p?.original === 'string' && typeof p?.translation === 'string');
            if (flat.length > 0) lines = [flat];
          }


          if (lines.length !== batch.length) {
            throw new Error(`AI returned wrong number of lines for ${label}: expected ${batch.length}, got ${lines.length}`);
          }

          if (!bestEffort) bestEffort = lines;

          for (let lineIndex = 0; lineIndex < lines.length; lineIndex++) {
            const problem = validateLine(batch[lineIndex], lines[lineIndex]);
            if (problem) {
              throw new Error(`AI returned ${problem} for ${label}, line ${lineIndex + 1}`);
            }
          }

          return lines;
        } catch (error) {
          lastError = error as Error;
          // Let the browser own long provider backoff so this request does not
          // exceed the edge runtime and leave the page stuck in processing.
          if (isRateLimit(error)) break;
          if (attempt < MAX_ATTEMPTS) {
            const wait = 600;
            console.log(`Retry ${attempt}/${MAX_ATTEMPTS} for ${label} in ${wait}ms: ${lastError.message}`);
            await sleep(wait);
          }
        }
      }

      // Rate limited even after backoff: bubble up so the caller saves progress
      // and the client resumes later. Splitting here would only add more load.
      if (isRateLimit(lastError)) throw lastError;

      // Fallback: the model mis-grouped lines — split the batch and try smaller chunks
      // (sequentially, to keep provider load low)
      if (batch.length > 1) {
        console.log(`Splitting ${label} after failures: ${lastError?.message}`);
        const mid = Math.ceil(batch.length / 2);
        const a = await translateBatch(batch.slice(0, mid), `${label} (a)`);
        const b = await translateBatch(batch.slice(mid), `${label} (b)`);
        return [...a, ...b];
      }

      // Single line that keeps failing: split the line itself, translate the chunks,
      // then merge their pairs back into ONE line so alignment stays word-level.
      const chunks = splitLine(batch[0]);
      if (chunks.length > 1) {
        console.log(`Splitting single line of ${label} into ${chunks.length} chunks: ${lastError?.message}`);
        const chunkResults: any[] = [];
        for (let i = 0; i < chunks.length; i++) {
          chunkResults.push(await translateBatch([chunks[i]], `${label} chunk ${i + 1}`));
        }
        return [chunkResults.flat(2)];
      }

      // Last resort: accept the best alignment the model produced. Throwing here
      // made the page loop forever on one stubborn line without ever advancing.
      if (bestEffort) {
        console.log(`Accepting best-effort alignment for ${label}: ${lastError?.message}`);
        return bestEffort;
      }

      throw lastError ?? new Error(`Unable to produce word-level alignment for ${label}`);
    };




    // Merge with whatever another invocation may have written meanwhile,
    // then write back positionally (never append).
    const persist = async (status: string) => {
      const { data: fresh } = await supabaseClient
        .from('pages')
        .select('translated_data')
        .eq('id', pageId)
        .single();
      const remote = (fresh?.translated_data as any)?.lines;
      if (Array.isArray(remote)) {
        for (let i = 0; i < Math.min(remote.length, textLines.length); i++) {
          if (!isDone(i) && Array.isArray(remote[i]) && remote[i].length > 0) {
            translatedLines[i] = remote[i];
          }
        }
      }
      const lines: any[] = [];
      for (let i = 0; i < textLines.length; i++) lines[i] = isDone(i) ? translatedLines[i] : null;
      await supabaseClient
        .from('pages')
        .update({ translated_data: { lines, fullTranslation: buildFullTranslation() }, status })
        .eq('id', pageId);
    };

    let cursor = startIndex;
    while (cursor < textLines.length) {
      if (Date.now() - START_TIME > TIME_BUDGET_MS) {
        partial = true;
        console.log(`Time budget reached at line ${cursor}/${textLines.length} — will resume`);
        break;
      }

      // Build up to CONCURRENCY batches and translate them in parallel
      const jobs: { start: number; end: number; batch: string[]; label: string }[] = [];
      let scan = cursor;
      while (scan < textLines.length && jobs.length < CONCURRENCY) {
        while (scan < textLines.length && isDone(scan)) scan++;
        if (scan >= textLines.length) break;
        const start = scan;
        let end = start;
        while (end < textLines.length && end - start < BATCH_SIZE && !isDone(end)) end++;
        jobs.push({ start, end, batch: textLines.slice(start, end), label: `batch ${start + 1}-${end}` });
        scan = end;
      }
      if (jobs.length === 0) break;

      console.log(`Translating ${jobs.map(j => j.label).join(', ')} of ${textLines.length} lines...`);
      const results = await Promise.allSettled(jobs.map(j => translateBatch(j.batch, j.label)));

      let failure: unknown = null;
      results.forEach((result, jobIndex) => {
        const job = jobs[jobIndex];
        if (result.status === 'fulfilled') {
          // Positional assignment keeps every translation glued to its source line
          for (let i = 0; i < job.batch.length; i++) {
            const line = result.value[i];
            if (Array.isArray(line) && line.length > 0) translatedLines[job.start + i] = line;
          }
        } else if (!failure) {
          failure = result.reason;
        }
      });
      cursor = scan;

      if (doneCount() > 0) await persist('processing');

      if (failure) {
        console.log(`Translation interrupted at line ${cursor}/${textLines.length}: ${failure instanceof Error ? failure.message : String(failure)}`);
        return new Response(
          JSON.stringify({
            success: true,
            partial: true,
            rateLimited: isRateLimit(failure),
            done: doneCount(),
            total: textLines.length,
            retryAfterMs: isRateLimit(failure) ? Math.max((failure as any).retryAfterMs || 0, 5000) : 0,
            error: failure instanceof Error ? failure.message : String(failure),
          }),
          { headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
        );
      }
    }


    if (firstMissing() < textLines.length) partial = true;

    if (partial) {
      console.log(`Partial translation saved: ${doneCount()}/${textLines.length} lines`);
      return new Response(
        JSON.stringify({ success: true, partial: true, done: doneCount(), total: textLines.length }),
        { headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      );
    }

    console.log('All lines translated successfully');

    // Combine into final format
    const translatedData = {
      lines: translatedLines.slice(0, textLines.length),
      fullTranslation: buildFullTranslation()
    };



    // Update page with translation
    await supabaseClient
      .from('pages')
      .update({ 
        translated_data: translatedData,
        status: 'completed'
      })
      .eq('id', pageId);

    // Update daily translation counter
    await supabaseClient
      .from('profiles')
      .update({
        daily_translations_count: dailyCount + 1,
        last_translation_date: today
      })
      .eq('id', userId);
    
    console.log(`Daily translations: ${dailyCount + 1}/100`);

    console.log('Page translation completed:', pageId);

    return new Response(
      JSON.stringify({ success: true, data: translatedData }),
      { headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );

  } catch (error) {
    console.error('Error translating page:', error);
    
    // Try to update page status to failed
    if (pageId) {
      try {
        const supabaseClient = createClient(
          Deno.env.get('SUPABASE_URL') ?? '',
          Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? ''
        );
        await supabaseClient
          .from('pages')
          .update({ status: 'failed' })
          .eq('id', pageId);
      } catch (e) {
        console.error('Failed to update page status:', e);
      }
    }

    return new Response(
      JSON.stringify({ error: error instanceof Error ? error.message : 'Unknown error' }),
      { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  }
});