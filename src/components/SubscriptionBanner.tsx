import { useSubscription } from '@/contexts/SubscriptionContext';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Crown, Sparkles } from 'lucide-react';

export const SubscriptionBanner = () => {
  const { billingEnabled, subscribed, freePages, loading, handleCheckout, handlePortal } = useSubscription();

  // Billing is optional (STRIPE_SECRET_KEY on the API); without it there are no limits to show.
  if (loading || !billingEnabled) return null;

  if (subscribed) {
    return (
      <Card className="bg-gradient-to-r from-primary/10 to-accent/10 border-primary/20">
        <CardContent className="flex items-center justify-between p-4">
          <div className="flex items-center gap-3">
            <Crown className="h-5 w-5 text-primary" />
            <div>
              <p className="font-semibold text-foreground">LexMatches Premium Active</p>
              <p className="text-sm text-muted-foreground">Unlimited translations</p>
            </div>
          </div>
          <Button variant="outline" onClick={handlePortal}>
            Manage Subscription
          </Button>
        </CardContent>
      </Card>
    );
  }

  const remainingPages = Math.max(0, 2 - freePages);

  return (
    <Card className="bg-gradient-to-r from-accent/10 to-secondary/10 border-accent/20">
      <CardContent className="flex items-center justify-between p-4">
        <div className="flex items-center gap-3">
          <Sparkles className="h-5 w-5 text-accent" />
          <div>
            <p className="font-semibold text-foreground">
              {remainingPages > 0 ? `${remainingPages} Free Page${remainingPages > 1 ? 's' : ''} Remaining` : 'Free Trial Complete'}
            </p>
            <p className="text-sm text-muted-foreground">
              {remainingPages > 0 ? 'Upgrade for unlimited translations' : 'Subscribe to continue translating'}
            </p>
          </div>
        </div>
        <Button onClick={handleCheckout} className="bg-primary hover:bg-primary/90">
          Upgrade to Premium - €3/mo
        </Button>
      </CardContent>
    </Card>
  );
};
