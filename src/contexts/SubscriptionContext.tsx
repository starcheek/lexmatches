import React, { createContext, useContext, useState, useEffect } from 'react';
import { toast } from 'sonner';
import { api, isLoggedIn } from '@/lib/api';

interface SubscriptionContextType {
  billingEnabled: boolean;
  subscribed: boolean;
  freePages: number;
  loading: boolean;
  checkSubscription: () => Promise<void>;
  handleCheckout: () => Promise<void>;
  handlePortal: () => Promise<void>;
}

const SubscriptionContext = createContext<SubscriptionContextType | undefined>(undefined);

export const SubscriptionProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [billingEnabled, setBillingEnabled] = useState(false);
  const [subscribed, setSubscribed] = useState(false);
  const [freePages, setFreePages] = useState(0);
  const [loading, setLoading] = useState(true);

  const checkSubscription = async () => {
    try {
      if (!isLoggedIn()) {
        setSubscribed(false);
        setFreePages(0);
        return;
      }
      const data = await api.getSubscription();
      setBillingEnabled(data.billing_enabled);
      setSubscribed(data.subscribed);
      setFreePages(data.freePages || 0);
    } catch (error) {
      console.error('Error checking subscription:', error); // silent: billing is optional
    } finally {
      setLoading(false);
    }
  };

  const handleCheckout = async () => {
    try {
      const data = await api.createCheckout();
      if (data?.url) window.open(data.url, '_blank');
    } catch (error) {
      console.error('Error creating checkout:', error);
      toast.error('Failed to create checkout session');
    }
  };

  const handlePortal = async () => {
    try {
      const data = await api.customerPortal();
      if (data?.url) window.open(data.url, '_blank');
    } catch (error) {
      console.error('Error opening portal:', error);
      toast.error('Failed to open customer portal');
    }
  };

  useEffect(() => {
    checkSubscription();
    // Poll every minute (only matters when billing is enabled)
    const interval = setInterval(checkSubscription, 60000);
    return () => clearInterval(interval);
  }, []);

  return (
    <SubscriptionContext.Provider
      value={{ billingEnabled, subscribed, freePages, loading, checkSubscription, handleCheckout, handlePortal }}
    >
      {children}
    </SubscriptionContext.Provider>
  );
};

// eslint-disable-next-line react-refresh/only-export-components -- hook belongs with its provider
export const useSubscription = () => {
  const context = useContext(SubscriptionContext);
  if (context === undefined) {
    throw new Error('useSubscription must be used within a SubscriptionProvider');
  }
  return context;
};
