/**
 * @typedef {Object} Project
 * @property {string} id
 * @property {string} [title]
 * @property {string} [status]
 * @property {string} [created_at]
 * @property {string} [updated_at]
 */

/**
 * @typedef {Object} Fact
 * @property {string} id
 * @property {string} [description]
 * @property {string} [created_at]
 * @property {string} [creator]
 */

/**
 * @typedef {Object} Intent
 * @property {string} id
 * @property {string[]} from
 * @property {string} [to]
 * @property {string} [description]
 * @property {string} [status]
 * @property {string} [worker]
 */

/**
 * @typedef {Object} LlmExecution
 * @property {string} id
 * @property {string} [task_type]
 * @property {string} [intent_id]
 * @property {string} [process_state]
 * @property {number} [event_count]
 * @property {string} [started_at]
 * @property {string} [ended_at]
 */

/**
 * @typedef {Object} LlmEvent
 * @property {number} sequence
 * @property {string} [execution_id]
 * @property {string} [event_kind]
 * @property {string} [kind]
 * @property {string} [content]
 * @property {string} [created_at]
 * @property {string} [phase]
 */

/**
 * @typedef {Object} Capability
 * @property {string} id
 * @property {string} name
 * @property {'mcp_server'|'skill'|string} kind
 * @property {boolean} [available]
 * @property {string} [description]
 */

export {};
