// Local pipeline smoke test: sign up dev user -> upload 2-page PDF -> process-pdf -> translate-page.
// Requires `npm run db:start` and `npm run functions`.
import { createClient } from '@supabase/supabase-js';
import { PDFDocument, StandardFonts } from 'pdf-lib';

const URL = 'http://127.0.0.1:54321';
const ANON = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6ImFub24iLCJleHAiOjE5ODM4MTI5OTZ9.CRXP1A7WOeoJeXxjNni43kdQwgnWNReilDMblYTn_I0';
const sb = createClient(URL, ANON, { auth: { persistSession: false } });

const email = 'dev@lexmatches.local', password = 'devpassword';
let { data: auth, error } = await sb.auth.signInWithPassword({ email, password });
if (error) ({ data: auth, error } = await sb.auth.signUp({ email, password }));
if (error) throw error;
const uid = auth.user.id;
console.log('user', uid);

const doc = await PDFDocument.create();
const font = await doc.embedFont(StandardFonts.Helvetica);
for (const t of ['Le chat est sur la table.\nIl mange une pomme de terre.', 'La technologie a réussi.\nNous allons à la plage.']) {
  doc.addPage([595, 842]).drawText(t, { x: 50, y: 780, size: 14, font, lineHeight: 20 });
}
const bytes = await doc.save();

const { data: book, error: be } = await sb.from('books').insert({ user_id: uid, title: 'Smoke test', original_locale: 'fr', target_locale: 'en' }).select().single();
if (be) throw be;
const { error: ue } = await sb.storage.from('books').upload(`${uid}/${book.id}.pdf`, bytes, { contentType: 'application/pdf' });
if (ue) throw ue;

let r = await sb.functions.invoke('process-pdf', { body: { bookId: book.id } });
console.log('process-pdf', r.error ? await r.error.context?.text?.() ?? r.error.message : r.data);

const { data: pages } = await sb.from('pages').select('id,page_number,original_text').eq('book_id', book.id).order('page_number');
console.log('pages', pages.map(p => [p.page_number, p.original_text]));

r = await sb.functions.invoke('translate-page', { body: { pageId: pages[0].id } });
console.log('translate-page', r.error ? await r.error.context?.text?.() ?? r.error.message : JSON.stringify(r.data).slice(0, 400));
