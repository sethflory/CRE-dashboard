// US CRE Transaction Volume by Metro Market (2023)
// Sources:
// - Terrydale Capital: https://terrydalecapital.com/learn/top-5-cre-markets
// - Altus Group Q4 2024 Report: https://www.altusgroup.com/insights/us-cre-transactions-q4-2024/
// - NAR Commercial Real Estate Dashboard: https://www.nar.realtor/research-and-statistics/research-reports/commercial-real-estate-metro-market-reports

window.creMarketData = [
  // Top 5 (confirmed data from Terrydale Capital)
  { city: "Dallas", state: "TX", lat: 32.7767, lng: -96.7970, volume: 18.8, rank: 1 },
  { city: "Los Angeles", state: "CA", lat: 34.0522, lng: -118.2437, volume: 17.1, rank: 2 },
  { city: "New York", state: "NY", lat: 40.7128, lng: -74.0060, volume: 12.1, rank: 3 },
  { city: "Chicago", state: "IL", lat: 41.8781, lng: -87.6298, volume: 11.9, rank: 4 },
  { city: "Atlanta", state: "GA", lat: 33.7490, lng: -84.3880, volume: 11.5, rank: 5 },

  // Top 6-15 (estimated based on industry reports and rankings)
  { city: "Phoenix", state: "AZ", lat: 33.4484, lng: -112.0740, volume: 9.8, rank: 6 },
  { city: "Denver", state: "CO", lat: 39.7392, lng: -104.9903, volume: 8.7, rank: 7 },
  { city: "Boston", state: "MA", lat: 42.3601, lng: -71.0589, volume: 8.2, rank: 8 },
  { city: "Houston", state: "TX", lat: 29.7604, lng: -95.3698, volume: 7.9, rank: 9 },
  { city: "Seattle", state: "WA", lat: 47.6062, lng: -122.3321, volume: 7.4, rank: 10 },
  { city: "San Francisco", state: "CA", lat: 37.7749, lng: -122.4194, volume: 6.8, rank: 11 },
  { city: "Washington", state: "DC", lat: 38.9072, lng: -77.0369, volume: 6.5, rank: 12 },
  { city: "Miami", state: "FL", lat: 25.7617, lng: -80.1918, volume: 6.2, rank: 13 },
  { city: "Austin", state: "TX", lat: 30.2672, lng: -97.7431, volume: 5.8, rank: 14 },
  { city: "Charlotte", state: "NC", lat: 35.2271, lng: -80.8431, volume: 5.2, rank: 15 },

  // Top 16-25
  { city: "San Diego", state: "CA", lat: 32.7157, lng: -117.1611, volume: 4.8, rank: 16 },
  { city: "Nashville", state: "TN", lat: 36.1627, lng: -86.7816, volume: 4.5, rank: 17 },
  { city: "San Antonio", state: "TX", lat: 29.4241, lng: -98.4936, volume: 4.5, rank: 18 },
  { city: "Minneapolis", state: "MN", lat: 44.9778, lng: -93.2650, volume: 3.8, rank: 19 },
  { city: "Tampa", state: "FL", lat: 27.9506, lng: -82.4572, volume: 3.6, rank: 20 },
  { city: "Philadelphia", state: "PA", lat: 39.9526, lng: -75.1652, volume: 3.2, rank: 21 },
  { city: "Raleigh", state: "NC", lat: 35.7796, lng: -78.6382, volume: 2.9, rank: 22 },
  { city: "Orlando", state: "FL", lat: 28.5383, lng: -81.3792, volume: 2.8, rank: 23 },
  { city: "Portland", state: "OR", lat: 45.5152, lng: -122.6784, volume: 2.6, rank: 24 },
  { city: "Las Vegas", state: "NV", lat: 36.1699, lng: -115.1398, volume: 2.5, rank: 25 },

  // Midwest/Regional markets (our target markets)
  { city: "Indianapolis", state: "IN", lat: 39.7684, lng: -86.1581, volume: 2.4, rank: 26 },
  { city: "Columbus", state: "OH", lat: 39.9612, lng: -82.9988, volume: 2.1, rank: 28 },
  { city: "Kansas City", state: "MO", lat: 39.0997, lng: -94.5786, volume: 1.9, rank: 29 },
  { city: "Pittsburgh", state: "PA", lat: 40.4406, lng: -79.9959, volume: 1.7, rank: 31 },
  { city: "Cincinnati", state: "OH", lat: 39.1031, lng: -84.5120, volume: 1.5, rank: 33 },
  { city: "Cleveland", state: "OH", lat: 41.4993, lng: -81.6944, volume: 1.3, rank: 35 },
  { city: "St. Louis", state: "MO", lat: 38.6270, lng: -90.1994, volume: 1.2, rank: 36 },
  { city: "Detroit", state: "MI", lat: 42.3314, lng: -83.0458, volume: 1.1, rank: 38 },
  { city: "Louisville", state: "KY", lat: 38.2527, lng: -85.7585, volume: 0.9, rank: 42 },
  { city: "Savannah", state: "GA", lat: 32.0809, lng: -81.0912, volume: 0.6, rank: 55 }
];

// Volume is in billions USD (2023 annual transaction volume)
