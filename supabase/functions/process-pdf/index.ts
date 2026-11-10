import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.39.3";
import { extractText } from "https://esm.sh/unpdf@0.11.0";

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
};

serve(async (req) => {
  if (req.method === 'OPTIONS') {
    return new Response(null, { headers: corsHeaders });
  }

  try {
    const supabaseClient = createClient(
      Deno.env.get('SUPABASE_URL') ?? '',
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? ''
    );

    const { bookId } = await req.json();
    console.log('Processing PDF for book:', bookId);

    // Get book details
    const { data: book, error: bookError } = await supabaseClient
      .from('books')
      .select('*')
      .eq('id', bookId)
      .single();

    if (bookError) throw bookError;

    // Update book status to processing
    await supabaseClient
      .from('books')
      .update({ status: 'processing' })
      .eq('id', bookId);

    // Get the PDF file from storage
    const { data: fileData, error: storageError } = await supabaseClient
      .storage
      .from('books')
      .download(`${book.user_id}/${bookId}.pdf`);

    if (storageError) throw storageError;

    if (!fileData) {
      throw new Error('Failed to download PDF file');
    }

    console.log('PDF downloaded, extracting text and images...');

    let pages: string[] = [];
    let totalPages = 0;
    
    try {
      // Convert blob to array buffer
      const arrayBuffer = await fileData.arrayBuffer();
      
      // Extract text using unpdf
      const result = await extractText(new Uint8Array(arrayBuffer), { mergePages: false });
      
      totalPages = result.totalPages;
      console.log(`PDF extracted: ${totalPages} pages`);
      
      // Check page limit to prevent timeouts
      const MAX_PAGES = 150;
      if (totalPages > MAX_PAGES) {
        await supabaseClient
          .from('books')
          .update({ status: 'failed' })
          .eq('id', bookId);
        
        throw new Error(`PDF has ${totalPages} pages. Maximum supported is ${MAX_PAGES} pages. Please split your PDF into smaller files.`);
      }
      
      // Get text array (each element is a page)
      pages = result.text.map((text: string) => text.trim()).filter((text: string) => text.length > 0);
      
      if (pages.length === 0) {
        throw new Error('No text content found in PDF');
      }
      
      console.log(`Extracted text from ${pages.length} pages`);
    } catch (pdfError) {
      console.error('PDF parsing error:', pdfError);
      await supabaseClient
        .from('books')
        .update({ status: 'failed' })
        .eq('id', bookId);
      throw pdfError;
    }
    
    // Create page records in efficient batches
    const batchSize = 100;
    for (let i = 0; i < pages.length; i += batchSize) {
      const batch = pages.slice(i, i + batchSize);
      const pageRecords = batch.map((text, idx) => ({
        book_id: bookId,
        page_number: i + idx + 1,
        original_text: text,
        status: 'pending'
      }));
      
      const { error: pageError } = await supabaseClient
        .from('pages')
        .insert(pageRecords);

      if (pageError) {
        console.error('Error creating page batch:', pageError);
      }
    }

    // Update book with total pages and status
    await supabaseClient
      .from('books')
      .update({ 
        total_pages: pages.length,
        status: 'completed'
      })
      .eq('id', bookId);
      
    console.log(`Successfully processed ${pages.length} pages for book ${bookId}`);

    return new Response(
      JSON.stringify({ success: true, pages: pages.length }),
      { headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );

  } catch (error) {
    console.error('Error processing PDF:', error);
    return new Response(
      JSON.stringify({ error: error instanceof Error ? error.message : 'Unknown error' }),
      { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    );
  }
});