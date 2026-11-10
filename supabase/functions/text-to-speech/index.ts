import { serve } from "https://deno.land/std@0.168.0/http/server.ts";
import { encodeBase64 } from "https://deno.land/std@0.224.0/encoding/base64.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

// Language to voice mapping - using multilingual voices that work with eleven_turbo_v2_5
const VOICE_MAP: Record<string, string> = {
  en: "9BWtsMINqrJLrRacOk9x", // Aria - English native
  fr: "JBFqnCBsd6RMkjVDRZzb", // George - French/multilingual
  pt: "Xb7hH8MSUJpSbSDYk0k2", // Alice - Portuguese/multilingual
  ru: "JBFqnCBsd6RMkjVDRZzb", // George - Russian/multilingual
  ja: "SAz9YHcvj6GT2YYXdXww", // River - Japanese/multilingual
  lv: "XB0fDUnXU5powFXDhCwa", // Charlotte - Latvian/multilingual (fallback)
};

serve(async (req) => {
  // Handle CORS preflight requests
  if (req.method === "OPTIONS") {
    return new Response(null, { headers: corsHeaders });
  }

  try {
    const { text, language } = await req.json();

    if (!text) {
      throw new Error("Text is required");
    }

    const ELEVENLABS_API_KEY = Deno.env.get("ELEVENLABS_API_KEY");
    if (!ELEVENLABS_API_KEY) {
      throw new Error("ElevenLabs API key not configured");
    }

    // Get voice ID based on language, default to English
    const langCode = language?.toLowerCase()?.substring(0, 2) || "en";
    const voiceId = VOICE_MAP[langCode] || VOICE_MAP["en"];

    console.log(`TTS request: language=${langCode}, voiceId=${voiceId}, textLength=${text.length}`);

    // Call ElevenLabs API
    const response = await fetch(
      `https://api.elevenlabs.io/v1/text-to-speech/${voiceId}`,
      {
        method: "POST",
        headers: {
          "Accept": "audio/mpeg",
          "Content-Type": "application/json",
          "xi-api-key": ELEVENLABS_API_KEY,
        },
        body: JSON.stringify({
          text,
          model_id: "eleven_turbo_v2_5", // Cheapest multilingual model - low latency
          voice_settings: {
            stability: 0.5,
            similarity_boost: 0.75,
          },
        }),
      }
    );

    if (!response.ok) {
      const errorText = await response.text();
      console.error("ElevenLabs API error:", response.status, errorText);
      throw new Error(`ElevenLabs API error: ${response.status}`);
    }

    // Convert audio to base64 using Deno's built-in encoder (handles large files)
    const arrayBuffer = await response.arrayBuffer();
    const base64Audio = encodeBase64(arrayBuffer);

    console.log(`TTS success: audioSize=${arrayBuffer.byteLength} bytes`);

    return new Response(
      JSON.stringify({ 
        audioContent: base64Audio,
        format: "mp3"
      }),
      {
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      }
    );
  } catch (error) {
    console.error("TTS error:", error);
    const errorMessage = error instanceof Error ? error.message : "Unknown error";
    return new Response(
      JSON.stringify({ error: errorMessage }),
      {
        status: 400,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
      }
    );
  }
});
