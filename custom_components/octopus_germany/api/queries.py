"""GraphQL query documents used by the Octopus Germany API client."""

ACCOUNT_DISCOVERY_QUERY = """
query {
  viewer {
    accounts {
      number
      status
      ledgers {
        balance
        ledgerType
      }
    }
  }
}
"""

ACCOUNT_DISCOVERY_QUERY_LEGACY = """
query {
  viewer {
    accounts {
      number
      ledgers {
        balance
        ledgerType
      }
    }
  }
}
"""

ACCOUNT_CAPABILITIES_QUERY = """
query AccountCapabilities($accountNumber: String!) {
  account(accountNumber: $accountNumber) {
    allProperties {
      electricityMalos {
        agreements {
          product {
            code
            description
            fullName
            isTimeOfUse
          }
        }
        meters {
          shouldReceiveSmartMeterData
          meloNumber
        }
      }
    }
  }
  devices(accountNumber: $accountNumber) {
    id
  }
}
"""

INTELLIGENT_DATA_QUERY = """
query IntelligentDataQuery($accountNumber: String!) {
  completedDispatches(accountNumber: $accountNumber) {
    delta
    deltaKwh
    end
    endDt
    meta { location source }
    start
    startDt
  }
  devices(accountNumber: $accountNumber) {
    id
    name
    deviceType
    provider
    integrationDeviceId
    status {
      current
      currentState
      isSuspended
      ... on SmartFlexVehicleStatus {
        activePower { value timestamp }
        stateOfCharge { value timestamp }
        stateOfChargeLimit {
          upperSocLimit
          timestamp
          isLimitViolated
        }
      }
      ... on SmartFlexChargePointStatus {
        stateOfCharge { value timestamp }
        stateOfChargeLimit {
          upperSocLimit
          timestamp
          isLimitViolated
        }
      }
    }
    preferences {
      mode
      targetType
      unit
      gridExport
      schedules { dayOfWeek max min time }
    }
    preferenceSetting {
      deviceType
      id
      mode
      unit
      scheduleSettings {
        id
        max
        min
        step
        timeFrom
        timeStep
        timeTo
      }
    }
    alerts { message publishedAt }
    ... on SmartFlexVehicle {
      vehicleVariant { model batterySize }
      chargingSessions(first: 100) {
        edges {
          node {
            start
            end
            stateOfChargeChange
            stateOfChargeFinal
            energyAdded { value unit }
            cost { amount currency }
            ... on SmartFlexChargingSession { type }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
    ... on SmartFlexChargePoint {
      chargingSessions(first: 100) {
        edges {
          node {
            start
            end
            stateOfChargeChange
            stateOfChargeFinal
            energyAdded { value unit }
            cost { amount currency }
            ... on SmartFlexChargingSession { type }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""

COMPREHENSIVE_QUERY = """
query ComprehensiveDataQuery($accountNumber: String!, $includeIntelligent: Boolean!) {
  account(accountNumber: $accountNumber) {
    id
    ledgers {
      balance
      ledgerType
    }
    allProperties {
      id
      electricityMalos {
        agreements {
          product {
            code
            description
            fullName
            isTimeOfUse
          }
          unitRateGrossRateInformation {
            grossRate
          }
          unitRateInformation {
            ... on SimpleProductUnitRateInformation {
              __typename
              grossRateInformation {
                date
                grossRate
                rateValidToDate
                vatRate
              }
              latestGrossUnitRateCentsPerKwh
              netUnitRateCentsPerKwh
            }
            ... on TimeOfUseProductUnitRateInformation {
              __typename
              rates {
                grossRateInformation {
                  date
                  grossRate
                  rateValidToDate
                  vatRate
                }
                latestGrossUnitRateCentsPerKwh
                netUnitRateCentsPerKwh
                timeslotActivationRules {
                  activeFromTime
                  activeToTime
                }
                timeslotName
              }
            }
          }
          unitRateForecast {
            validFrom
            validTo
            unitRateInformation {
              __typename
              ... on SimpleProductUnitRateInformation {
                latestGrossUnitRateCentsPerKwh
              }
              ... on TimeOfUseProductUnitRateInformation {
                rates {
                  latestGrossUnitRateCentsPerKwh
                }
              }
            }
          }
          validFrom
          validTo
        }
        maloNumber
                meters {
          id
          meterType
          number
                    meloNumber
          shouldReceiveSmartMeterData
          submitMeterReadingUrl
        }
        referenceConsumption
      }
      gasMalos {
        agreements {
          product {
            code
            description
            fullName
            isTimeOfUse
          }
          unitRateGrossRateInformation {
            grossRate
          }
          unitRateInformation {
            ... on SimpleProductUnitRateInformation {
              __typename
              grossRateInformation {
                date
                grossRate
                rateValidToDate
                vatRate
              }
              latestGrossUnitRateCentsPerKwh
              netUnitRateCentsPerKwh
            }
            ... on TimeOfUseProductUnitRateInformation {
              __typename
              rates {
                grossRateInformation {
                  date
                  grossRate
                  rateValidToDate
                  vatRate
                }
                latestGrossUnitRateCentsPerKwh
                netUnitRateCentsPerKwh
                timeslotActivationRules {
                  activeFromTime
                  activeToTime
                }
                timeslotName
              }
            }
          }
          validFrom
          validTo
        }
        maloNumber
                meters {
          id
          meterType
          number
                    meloNumber
          shouldReceiveSmartMeterData
          submitMeterReadingUrl
        }
        referenceConsumption
      }
    }
  }
    completedDispatches(accountNumber: $accountNumber) @include(if: $includeIntelligent) {
    delta
    deltaKwh
    end
    endDt
    meta {
      location
      source
    }
    start
    startDt
  }
    devices(accountNumber: $accountNumber) @include(if: $includeIntelligent) {
    status {
      current
      currentState
      isSuspended
      ... on SmartFlexVehicleStatus {
                activePower {
                    value
                    timestamp
                }
                stateOfCharge {
                    value
                    timestamp
                }
                stateOfChargeLimit {
                    upperSocLimit
                    timestamp
                    isLimitViolated
                }
      }
      ... on SmartFlexChargePointStatus {
                stateOfCharge {
                    value
                    timestamp
                }
                stateOfChargeLimit {
                    upperSocLimit
                    timestamp
                    isLimitViolated
                }
      }
    }
    provider
    preferences {
      mode
      schedules {
        dayOfWeek
        max
        min
        time
      }
      targetType
      unit
      gridExport
    }
    preferenceSetting {
      deviceType
      id
      mode
      scheduleSettings {
        id
        max
        min
        step
        timeFrom
        timeStep
        timeTo
      }
      unit
    }
    name
    integrationDeviceId
    id
    deviceType
    alerts {
      message
      publishedAt
    }
    ... on SmartFlexVehicle {
      id
      name
      status {
        current
        currentState
        isSuspended
                ... on SmartFlexVehicleStatus {
                    activePower {
                        value
                        timestamp
                    }
                    stateOfCharge {
                        value
                        timestamp
                    }
                    stateOfChargeLimit {
                        upperSocLimit
                        timestamp
                        isLimitViolated
                    }
                }
      }
      vehicleVariant { model batterySize }
      chargingSessions(first: 100) {
        edges {
          node {
            start
            end
                        stateOfChargeChange
                        stateOfChargeFinal
            energyAdded {
              value
              unit
            }
            cost {
              amount
              currency
            }
            ... on SmartFlexChargingSession {
              type
            }
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
    ... on SmartFlexChargePoint {
      chargingSessions(first: 100) {
        edges {
          node {
            start
            end
                        stateOfChargeChange
                        stateOfChargeFinal
            energyAdded {
              value
              unit
            }
            cost {
              amount
              currency
            }
            ... on SmartFlexChargingSession {
              type
            }
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
  }
}
"""

# Query to get latest gas meter readings
GAS_METER_READINGS_QUERY = """
query GasMeterReadings($accountNumber: String!, $meterId: ID!) {
  gasMeterReadings(accountNumber: $accountNumber, meterId: $meterId, first: 1) {
    edges {
      node {
        value
        readAt
        registerObisCode
        typeOfRead
        origin
        meterId
      }
    }
  }
}
"""

# Query to get latest electricity meter readings
ELECTRICITY_METER_READINGS_QUERY = """
query ElectricityMeterReadings($accountNumber: String!, $meterId: ID!) {
  electricityMeterReadings(accountNumber: $accountNumber, meterId: $meterId, first: 1) {
    edges {
      node {
        value
        readAt
        registerObisCode
        typeOfRead
        origin
        meterId
        registerType
      }
    }
  }
}
"""

# Query to get latest smart meter readings
# Schema introspection query to explore available fields
INTROSPECTION_QUERY = """
query IntrospectionQuery {
  __schema {
    types {
      name
      kind
      description
      fields {
        name
        description
        type {
          name
          kind
          ofType {
            name
            kind
          }
        }
      }
    }
  }
}
"""

# Property schema query to see what's available on properties
# Alternative queries to try different approaches for smart meter data
ALTERNATIVE_METER_READINGS_QUERY_1 = """
query getMeterReadings($accountNumber: String!, $propertyId: ID!) {
  account(accountNumber: $accountNumber) {
    property(id: $propertyId) {
      electricityMeterPoints {
        id
        mpan
        meterReadings(first: 24) {
          edges {
            node {
              readAt
              value
              unit
              readingSource
            }
          }
        }
        meters {
          id
          serialNumber
          smartMeter
        }
      }
    }
  }
}
"""

ALTERNATIVE_METER_READINGS_QUERY_2 = """
query getPropertyMeasurements($accountNumber: String!, $propertyId: ID!) {
  account(accountNumber: $accountNumber) {
    property(id: $propertyId) {
      id
      address {
        line1
        postcode
      }
      electricityMeterPoints {
        id
        mpan
        meters {
          id
          serialNumber
          smartMeter
          measurements(first: 24) {
            edges {
              node {
                ... on IntervalMeasurementType {
                  startAt
                  endAt
                  value
                  unit
                }
              }
            }
          }
        }
      }
    }
  }
}
"""

PROPERTY_SCHEMA_QUERY = """
query PropertySchema($accountNumber: String!, $propertyId: ID!) {
  account(accountNumber: $accountNumber) {
    property(id: $propertyId) {
      __typename
      id
            address
            electricityMalos {
                maloNumber
                meters {
                    id
                    number
                    meterType
                    meloNumber
                    shouldReceiveSmartMeterData
                }
            }
            gasMalos {
                maloNumber
                meters {
                    id
                    number
                    meterType
                    meloNumber
                    shouldReceiveSmartMeterData
                }
            }
    }
  }
}
"""

# Updated queries based on schema exploration
ELECTRICITY_SMART_METER_READINGS_QUERY_V2 = """
query getSmartMeterUsageV2($accountNumber: String!, $propertyId: ID!, $date: Date!) {
  account(accountNumber: $accountNumber) {
    property(id: $propertyId) {
      electricityMalos {
                meters {
          id
          number
          meterType
                    meloNumber
          shouldReceiveSmartMeterData
        }
        agreements {
          product {
            code
          }
        }
      }
      measurements(
        utilityFilters: {electricityFilters: {readingFrequencyType: HOUR_INTERVAL, readingQuality: COMBINED}}
        startOn: $date
        first: 24
      ) {
        edges {
          node {
            ... on IntervalMeasurementType {
              endAt
              startAt
              unit
              value
            }
          }
        }
      }
    }
  }
}
"""

# Query based on electricityMalos structure
ELECTRICITY_MALO_READINGS_QUERY = """
query getElectricityMaloReadings($accountNumber: String!, $propertyId: ID!) {
  account(accountNumber: $accountNumber) {
    property(id: $propertyId) {
      electricityMalos {
                meters {
          id
          number
          meterType
                    meloNumber
          shouldReceiveSmartMeterData
          registers {
            obisCode
            registerType
            readings(first: 24) {
              edges {
                node {
                  value
                  readAt
                  typeOfRead
                  origin
                }
              }
            }
          }
        }
      }
    }
  }
}
"""

ELECTRICITY_SMART_METER_READINGS_QUERY = """
query getSmartMeterUsage($accountNumber: String!, $propertyId: ID!, $date: Date!) {
  account(accountNumber: $accountNumber) {
    property(id: $propertyId) {
      measurements(
        utilityFilters: {electricityFilters: {readingFrequencyType: HOUR_INTERVAL, readingQuality: COMBINED}}
        startOn: $date
        first: 24
      ) {
        edges {
          node {
            ... on IntervalMeasurementType {
              endAt
              startAt
              unit
              value
            }
          }
        }
      }
    }
  }
}
"""

ELECTRICITY_15MIN_READINGS_QUERY = """
query getSmartMeter15Min($accountNumber: String!, $propertyId: ID!, $date: Date!) {
  account(accountNumber: $accountNumber) {
    property(id: $propertyId) {
      measurements(
        utilityFilters: {electricityFilters: {readingFrequencyType: RAW_INTERVAL, readingQuality: COMBINED}}
        startOn: $date
        first: 96
      ) {
        edges {
          node {
            ... on IntervalMeasurementType {
              endAt
              startAt
              unit
              value
            }
          }
        }
      }
    }
  }
}
"""

# Query to get vehicle device details with preference settings
VEHICLE_DETAILS_QUERY = """
query Vehicle($accountNumber: String = "") {
  devices(accountNumber: $accountNumber) {
    deviceType
    id
    integrationDeviceId
    name
    preferenceSetting {
      deviceType
      id
      mode
      scheduleSettings {
        id
        max
        min
        step
        timeFrom
        timeStep
        timeTo
      }
      unit
    }
    preferences {
      gridExport
      mode
      targetType
      unit
    }
  }
}
"""

# Query to get charging sessions for smart charging rewards tracking
CHARGING_SESSIONS_QUERY = """
query ChargingSessions($accountNumber: String!) {
  devices(accountNumber: $accountNumber) {
    id
    deviceType
    name
    ... on SmartFlexVehicle {
      chargingSessions(first: 100) {
        edges {
          node {
            start
            end
                        stateOfChargeChange
                        stateOfChargeFinal
            energyAdded {
              value
              unit
            }
            cost {
              amount
              currency
            }
            ... on SmartFlexChargingSession {
              type
            }
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
    ... on SmartFlexChargePoint {
      chargingSessions(first: 100) {
        edges {
          node {
            start
            end
                        stateOfChargeChange
                        stateOfChargeFinal
            energyAdded {
              value
              unit
            }
            cost {
              amount
              currency
            }
            ... on SmartFlexChargingSession {
              type
            }
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
  }
}
"""
