-- Add subscription and usage tracking to profiles
ALTER TABLE public.profiles 
ADD COLUMN stripe_customer_id text,
ADD COLUMN stripe_subscription_id text,
ADD COLUMN subscription_status text DEFAULT 'inactive',
ADD COLUMN pages_translated_free integer DEFAULT 0,
ADD COLUMN subscription_current_period_end timestamp with time zone;

-- Create index for faster subscription lookups
CREATE INDEX idx_profiles_stripe_customer ON public.profiles(stripe_customer_id);
CREATE INDEX idx_profiles_subscription_status ON public.profiles(subscription_status);