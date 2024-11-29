import { useRef, useState, useEffect } from "react";
import { Checkbox, Panel, DefaultButton, TextField, SpinButton } from "@fluentui/react";
import { SparkleFilled } from "@fluentui/react-icons";
import readNDJSONStream from "ndjson-readablestream";

import styles from "./Chat.module.css";

import {
    chatApi,
    configApi,
    RetrievalMode,
    ChatAppResponse,
    ChatAppResponseOrError,
    ChatAppRequest,
    ResponseMessage,
    VectorFieldOptions,
    GPT4VInput
} from "../../api";
import { Answer, AnswerError, AnswerLoading } from "../../components/Answer";
import { QuestionInput } from "../../components/QuestionInput";
import { ExampleList } from "../../components/Example";
import { UserChatMessage } from "../../components/UserChatMessage";
import { AnalysisPanel, AnalysisPanelTabs } from "../../components/AnalysisPanel";
import { SettingsButton } from "../../components/SettingsButton";
import { ClearChatButton } from "../../components/ClearChatButton";
import { useLogin, getToken, isLoggedIn, requireAccessControl } from "../../authConfig";
import { VectorSettings } from "../../components/VectorSettings";
import { useMsal } from "@azure/msal-react";
import { TokenClaimsDisplay } from "../../components/TokenClaimsDisplay";
import { GPT4VSettings } from "../../components/GPT4VSettings";

const Chat = () => {
    const categoryOptions = [
        { key: "Tip Sheet", text: "Tip Sheet" },
        { key: "Quick Start Guide", text: "Quick Start Guide" },
        { key: "Reference Guide", text: "Reference Guide" },
        { key: "FAQs", text: "FAQs" }
        //{ key: "Unknown", text: "Unknown" }
    ];

    const versionOptions = [
        { key: "2024Winter", text: "2024 Winter" },
        { key: "2024Summer", text: "2024 Summer" },
        { key: "2023Hyperdrive", text: "2023 Hyperdrive" },
        { key: "2023Summer", text: "2023 Summer" },
        { key: "2022Fall", text: "2022 Fall" },
        { key: "2022Spring", text: "2022 Spring" },
        { key: "2021Fall", text: "2021 Fall" },
        { key: "2021Spring", text: "2021 Spring" },
        { key: "2020Fall", text: "2020 Fall" },
        { key: "2020Spring", text: "2020 Spring" },
        { key: "2019", text: "2019" },
        { key: "2018", text: "2018" },
        { key: "2017", text: "2017" },
        { key: "2014", text: "2014" }
        //{ key: "None", text: "None" }
    ];

    const audienceOptions = [
        { key: "Ambulatory Clinicians", text: "Ambulatory Clinicians" },
        { key: "Ambulatory Providers", text: "Ambulatory Providers" },
        {
            key: "Ancillary Staff (PT, OT, SLP, Audiologist, Dietician, Social Worker or Chaplain)",
            text: "Ancillary Staff (PT, OT, SLP, Audiologist, Dietician, Social Worker or Chaplain)"
        },
        { key: "Behavioral Health Clinician", text: "Behavioral Health Clinician" },
        { key: "Charge Entry Staff", text: "Charge Entry Staff" },
        { key: "Claims Staff", text: "Claims Staff" },
        { key: "Clinical Staff (RN, LPN, MA or MTA)", text: "Clinical Staff (RN, LPN, MA or MTA)" },
        { key: "Customer Service Staff", text: "Customer Service Staff" },
        { key: "ED Clerk", text: "ED Clerk" },
        { key: "ED Nurse", text: "ED Nurse" },
        { key: "ED Provider", text: "ED Provider" },
        { key: "Front Desk", text: "Front Desk" },
        { key: "HIM", text: "HIM" },
        { key: "Home Health", text: "Home Health" },
        { key: "Home Infusion", text: "Home Infusion" },
        { key: "Hospice", text: "Hospice" },
        { key: "Hospice IPU", text: "Hospice IPU" },
        { key: "Informaticists", text: "Informaticists" },
        { key: "Inpatient Peds Extended Hours", text: "Inpatient Peds Extended Hours" },
        { key: "Insurance FollowUp Staff", text: "Insurance FollowUp Staff" },
        { key: "Managers", text: "Managers" },
        { key: "Medical Records/HIM Staff", text: "Medical Records/HIM Staff" },
        { key: "Oncology Staff", text: "Oncology Staff" },
        { key: "Other", text: "Other" },
        { key: "Patient Access Staff", text: "Patient Access Staff" },
        { key: "Pharmacist", text: "Pharmacist" },
        { key: "Pharmacy Tech", text: "Pharmacy Tech" },
        { key: "Providers (Attending, Resident, NP or PA)", text: "Providers (Attending, Resident, NP or PA)" },
        { key: "Registration", text: "Registration" },
        { key: "Scheduling", text: "Scheduling" },
        { key: "Technologist", text: "Technologist" }
    ];

    const [isConfigPanelOpen, setIsConfigPanelOpen] = useState(false);
    const [promptTemplate, setPromptTemplate] = useState<string>("");
    const [retrieveCount, setRetrieveCount] = useState<number>(3);
    const [retrievalMode, setRetrievalMode] = useState<RetrievalMode>(RetrievalMode.Hybrid);
    const [useSemanticRanker, setUseSemanticRanker] = useState<boolean>(true);
    const [shouldStream, setShouldStream] = useState<boolean>(false);
    const [useSemanticCaptions, setUseSemanticCaptions] = useState<boolean>(false);

    const [includeCategory, setIncludeCategory] = useState<string[]>([]); // Tracks unchecked categories
    const [includeVersion, setIncludeVersion] = useState(versionOptions.map(option => option.key)); // Tracks checked versions
    const [includeAudience, setIncludeAudience] = useState(audienceOptions.map(option => option.key)); // Tracks checked versions
    const [isAllCategoriesChecked, setIsAllCategoriesChecked] = useState(true); // Track if all are checked or not
    const [isAllVersionsChecked, setIsAllVersionsChecked] = useState(true);
    const [isAllAudienceChecked, setIsAllAudienceChecked] = useState(true);
    const [searchTerm, setSearchTerm] = useState<string>("");

    const [useSuggestFollowupQuestions, setUseSuggestFollowupQuestions] = useState<boolean>(false);
    const [vectorFieldList, setVectorFieldList] = useState<VectorFieldOptions[]>([VectorFieldOptions.Embedding]);
    const [useOidSecurityFilter, setUseOidSecurityFilter] = useState<boolean>(false);
    const [useGroupsSecurityFilter, setUseGroupsSecurityFilter] = useState<boolean>(false);
    const [gpt4vInput, setGPT4VInput] = useState<GPT4VInput>(GPT4VInput.TextAndImages);
    const [useGPT4V, setUseGPT4V] = useState<boolean>(false);

    const lastQuestionRef = useRef<string>("");
    const chatMessageStreamEnd = useRef<HTMLDivElement | null>(null);

    const [isLoading, setIsLoading] = useState<boolean>(false);
    const [isStreaming, setIsStreaming] = useState<boolean>(false);
    const [error, setError] = useState<unknown>();

    const [activeCitation, setActiveCitation] = useState<string>();
    const [activeAnalysisPanelTab, setActiveAnalysisPanelTab] = useState<AnalysisPanelTabs | undefined>(undefined);

    const [selectedAnswer, setSelectedAnswer] = useState<number>(0);
    const [answers, setAnswers] = useState<[user: string, response: ChatAppResponse][]>([]);
    const [streamedAnswers, setStreamedAnswers] = useState<[user: string, response: ChatAppResponse][]>([]);
    const [showGPT4VOptions, setShowGPT4VOptions] = useState<boolean>(false);

    const getConfig = async () => {
        const token = client ? await getToken(client) : undefined;

        configApi(token).then(config => {
            setShowGPT4VOptions(config.showGPT4VOptions);
        });
    };

    const handleAsyncRequest = async (question: string, answers: [string, ChatAppResponse][], setAnswers: Function, responseBody: ReadableStream<any>) => {
        let answer: string = "";
        let askResponse: ChatAppResponse = {} as ChatAppResponse;

        const updateState = (newContent: string) => {
            return new Promise(resolve => {
                setTimeout(() => {
                    answer += newContent;
                    const latestResponse: ChatAppResponse = {
                        ...askResponse,
                        choices: [{ ...askResponse.choices[0], message: { content: answer, role: askResponse.choices[0].message.role } }]
                    };
                    setStreamedAnswers([...answers, [question, latestResponse]]);
                    resolve(null);
                }, 33);
            });
        };
        try {
            setIsStreaming(true);
            for await (const event of readNDJSONStream(responseBody)) {
                if (event["choices"] && event["choices"][0]["context"] && event["choices"][0]["context"]["data_points"]) {
                    event["choices"][0]["message"] = event["choices"][0]["delta"];
                    askResponse = event;
                } else if (event["choices"] && event["choices"][0]["delta"]["content"]) {
                    setIsLoading(false);
                    await updateState(event["choices"][0]["delta"]["content"]);
                } else if (event["choices"] && event["choices"][0]["context"]) {
                    // Update context with new keys from latest event
                    askResponse.choices[0].context = { ...askResponse.choices[0].context, ...event["choices"][0]["context"] };
                } else if (event["error"]) {
                    throw Error(event["error"]);
                }
            }
        } finally {
            setIsStreaming(false);
        }
        const fullResponse: ChatAppResponse = {
            ...askResponse,
            choices: [{ ...askResponse.choices[0], message: { content: answer, role: askResponse.choices[0].message.role } }]
        };
        return fullResponse;
    };

    const client = useLogin ? useMsal().instance : undefined;

    const makeApiRequest = async (question: string) => {
        lastQuestionRef.current = question;

        error && setError(undefined);
        setIsLoading(true);
        setActiveCitation(undefined);
        setActiveAnalysisPanelTab(undefined);

        const token = client ? await getToken(client) : undefined;

        try {
            const messages: ResponseMessage[] = answers.flatMap(a => [
                { content: a[0], role: "user" },
                { content: a[1].choices[0].message.content, role: "assistant" },
                { content: a[1].choices[0].context.history, role: "history" }
            ]);

            const request: ChatAppRequest = {
                messages: [...messages, { content: question, role: "user" }],
                stream: shouldStream,
                context: {
                    overrides: {
                        prompt_template: promptTemplate.length === 0 ? undefined : promptTemplate,
                        include_category: includeCategory.length === 0 ? "" : includeCategory.join(","),
                        include_version: includeVersion.length === 0 ? "" : includeVersion.join(","),
                        include_audience: includeAudience.length === 0 ? "" : includeAudience.join("|"),
                        top: retrieveCount,
                        retrieval_mode: retrievalMode,
                        semantic_ranker: useSemanticRanker,
                        semantic_captions: useSemanticCaptions,
                        suggest_followup_questions: useSuggestFollowupQuestions,
                        use_oid_security_filter: useOidSecurityFilter,
                        use_groups_security_filter: useGroupsSecurityFilter,
                        vector_fields: vectorFieldList,
                        use_gpt4v: useGPT4V,
                        gpt4v_input: gpt4vInput
                    }
                },
                // ChatAppProtocol: Client must pass on any session state received from the server
                session_state: answers.length ? answers[answers.length - 1][1].choices[0].session_state : null
            };

            const response = await chatApi(request, token);
            if (!response.body) {
                throw Error("No response body");
            }
            if (shouldStream) {
                const parsedResponse: ChatAppResponse = await handleAsyncRequest(question, answers, setAnswers, response.body);
                setAnswers([...answers, [question, parsedResponse]]);
            } else {
                const parsedResponse: ChatAppResponseOrError = await response.json();
                if (response.status > 299 || !response.ok) {
                    throw Error(parsedResponse.error || "Unknown error");
                }
                setAnswers([...answers, [question, parsedResponse as ChatAppResponse]]);
            }
        } catch (e) {
            setError(e);
        } finally {
            setIsLoading(false);
        }
    };

    const clearChat = () => {
        lastQuestionRef.current = "";
        error && setError(undefined);
        setActiveCitation(undefined);
        setActiveAnalysisPanelTab(undefined);
        setAnswers([]);
        setStreamedAnswers([]);
        setIsLoading(false);
        setIsStreaming(false);
    };

    useEffect(() => chatMessageStreamEnd.current?.scrollIntoView({ behavior: "smooth" }), [isLoading]);
    useEffect(() => chatMessageStreamEnd.current?.scrollIntoView({ behavior: "auto" }), [streamedAnswers]);
    useEffect(() => {
        getConfig();
    }, []);

    const onPromptTemplateChange = (_ev?: React.FormEvent<HTMLInputElement | HTMLTextAreaElement>, newValue?: string) => {
        setPromptTemplate(newValue || "");
    };

    const onRetrieveCountChange = (_ev?: React.SyntheticEvent<HTMLElement, Event>, newValue?: string) => {
        setRetrieveCount(parseInt(newValue || "3"));
    };

    const onUseSemanticRankerChange = (_ev?: React.FormEvent<HTMLElement | HTMLInputElement>, checked?: boolean) => {
        setUseSemanticRanker(!!checked);
    };

    const onUseSemanticCaptionsChange = (_ev?: React.FormEvent<HTMLElement | HTMLInputElement>, checked?: boolean) => {
        setUseSemanticCaptions(!!checked);
    };

    const onShouldStreamChange = (_ev?: React.FormEvent<HTMLElement | HTMLInputElement>, checked?: boolean) => {
        setShouldStream(!!checked);
    };

    const handleToggleCheckAllCategories = () => {
        if (isAllCategoriesChecked) {
            setIncludeCategory(categoryOptions.map(option => option.key)); // Uncheck all
        } else {
            setIncludeCategory([]); // Check all
        }
        setIsAllCategoriesChecked(!isAllCategoriesChecked); // Toggle the state
    };

    const handleToggleCheckAllVersions = () => {
        if (isAllVersionsChecked) {
            setIncludeVersion([]); // Clear to indicate none are checked
        } else {
            setIncludeVersion(versionOptions.map(option => option.key)); // Track all versions as checked
        }
        setIsAllVersionsChecked(!isAllVersionsChecked);
    };

    const handleToggleCheckAllAudience = () => {
        if (isAllAudienceChecked) {
            setIncludeAudience([]); // Clear to indicate none are checked
        } else {
            setIncludeAudience(audienceOptions.map(option => option.key));
        }
        setIsAllAudienceChecked(!isAllAudienceChecked);
    };

    const otherOption = audienceOptions.find(option => option.key === "Other");
    const filteredAudienceOptions = audienceOptions.filter(option => option.text.toLowerCase().includes(searchTerm.toLowerCase()));
    const displayAudienceOptions = filteredAudienceOptions.length > 0 ? filteredAudienceOptions : otherOption ? [otherOption] : [];

    const onUseSuggestFollowupQuestionsChange = (_ev?: React.FormEvent<HTMLElement | HTMLInputElement>, checked?: boolean) => {
        setUseSuggestFollowupQuestions(!!checked);
    };

    const onUseOidSecurityFilterChange = (_ev?: React.FormEvent<HTMLElement | HTMLInputElement>, checked?: boolean) => {
        setUseOidSecurityFilter(!!checked);
    };

    const onUseGroupsSecurityFilterChange = (_ev?: React.FormEvent<HTMLElement | HTMLInputElement>, checked?: boolean) => {
        setUseGroupsSecurityFilter(!!checked);
    };

    const onExampleClicked = (example: string) => {
        makeApiRequest(example);
    };

    const onShowCitation = (citation: string, index: number) => {
        if (activeCitation === citation && activeAnalysisPanelTab === AnalysisPanelTabs.CitationTab && selectedAnswer === index) {
            setActiveAnalysisPanelTab(undefined);
        } else {
            setActiveCitation(citation);
            setActiveAnalysisPanelTab(AnalysisPanelTabs.CitationTab);
        }

        setSelectedAnswer(index);
    };

    const onToggleTab = (tab: AnalysisPanelTabs, index: number) => {
        if (activeAnalysisPanelTab === tab && selectedAnswer === index) {
            setActiveAnalysisPanelTab(undefined);
        } else {
            setActiveAnalysisPanelTab(tab);
        }

        setSelectedAnswer(index);
    };

    return (
        <div className={styles.container}>
            <div className={styles.commandsContainer}>
                <ClearChatButton className={styles.commandButton} onClick={clearChat} disabled={!lastQuestionRef.current || isLoading} />
                <SettingsButton className={styles.commandButton} onClick={() => setIsConfigPanelOpen(!isConfigPanelOpen)} />
            </div>
            <div className={styles.chatRoot}>
                <div className={styles.chatContainer}>
                    {!lastQuestionRef.current ? (
                        <div className={styles.chatEmptyState}>
                            {/* <SparkleFilled fontSize={"120px"} primaryFill={"rgba(115, 118, 225, 1)"} aria-hidden="true" aria-label="Chat logo" /> */}
                            <h1 className={styles.chatEmptyStateTitle}>Chat with Epic Tip Sheets</h1>
                            <h3 className={styles.chatTipsHeader}>Helpful Tips</h3> {/* New small header */}
                            <ul className={styles.chatTips}>
                                <li>
                                    <strong>Interact Like a Chatbot</strong>: Ask questions conversationally for the best responses.
                                </li>
                                <li>
                                    <strong>Include Details</strong>: Include relevant information about yourself (e.g., role, department) for more tailored
                                    results.
                                </li>
                                <li>
                                    <strong>Scroll to Verify</strong>: Check the full document citation for context and accuracy by scrolling down to the
                                    relevant section.
                                </li>
                                <li>
                                    <strong>Try Filters</strong>: Access filters for document type, audience, and Epic version under
                                    <strong>&nbsp;Search Settings&nbsp;</strong>
                                    to refine your results.
                                </li>
                            </ul>
                            <h2 className={styles.chatEmptyStateSubtitle}>Ask a question about Epic or try an example below to get started.</h2>
                            <ExampleList onExampleClicked={onExampleClicked} useGPT4V={useGPT4V} />
                        </div>
                    ) : (
                        <div className={styles.chatMessageStream}>
                            {isStreaming &&
                                streamedAnswers.map((streamedAnswer, index) => (
                                    <div key={index}>
                                        <UserChatMessage message={streamedAnswer[0]} />
                                        <div className={styles.chatMessageGpt}>
                                            <Answer
                                                isStreaming={true}
                                                key={index}
                                                answer={streamedAnswer[1]}
                                                isSelected={false}
                                                onCitationClicked={c => onShowCitation(c, index)}
                                                onThoughtProcessClicked={() => onToggleTab(AnalysisPanelTabs.ThoughtProcessTab, index)}
                                                onSupportingContentClicked={() => onToggleTab(AnalysisPanelTabs.SupportingContentTab, index)}
                                                onFollowupQuestionClicked={q => makeApiRequest(q)}
                                                showFollowupQuestions={useSuggestFollowupQuestions && answers.length - 1 === index}
                                            />
                                        </div>
                                    </div>
                                ))}
                            {!isStreaming &&
                                answers.map((answer, index) => (
                                    <div key={index}>
                                        <UserChatMessage message={answer[0]} />
                                        <div className={styles.chatMessageGpt}>
                                            <Answer
                                                isStreaming={false}
                                                key={index}
                                                answer={answer[1]}
                                                isSelected={selectedAnswer === index && activeAnalysisPanelTab !== undefined}
                                                onCitationClicked={c => onShowCitation(c, index)}
                                                onThoughtProcessClicked={() => onToggleTab(AnalysisPanelTabs.ThoughtProcessTab, index)}
                                                onSupportingContentClicked={() => onToggleTab(AnalysisPanelTabs.SupportingContentTab, index)}
                                                onFollowupQuestionClicked={q => makeApiRequest(q)}
                                                showFollowupQuestions={useSuggestFollowupQuestions && answers.length - 1 === index}
                                            />
                                        </div>
                                    </div>
                                ))}
                            {isLoading && (
                                <>
                                    <UserChatMessage message={lastQuestionRef.current} />
                                    <div className={styles.chatMessageGptMinWidth}>
                                        <AnswerLoading />
                                    </div>
                                </>
                            )}
                            {error ? (
                                <>
                                    <UserChatMessage message={lastQuestionRef.current} />
                                    <div className={styles.chatMessageGptMinWidth}>
                                        <AnswerError error={error.toString()} onRetry={() => makeApiRequest(lastQuestionRef.current)} />
                                    </div>
                                </>
                            ) : null}
                            <div ref={chatMessageStreamEnd} />
                        </div>
                    )}

                    <div className={styles.chatInput}>
                        <QuestionInput
                            clearOnSend
                            placeholder="Type a new question (e.g. How do I designate a POA?)"
                            disabled={isLoading}
                            onSend={question => makeApiRequest(question)}
                        />
                    </div>
                </div>

                {answers.length > 0 && activeAnalysisPanelTab && (
                    <AnalysisPanel
                        className={styles.chatAnalysisPanel}
                        activeCitation={activeCitation}
                        onActiveTabChanged={x => onToggleTab(x, selectedAnswer)}
                        citationHeight="810px"
                        answer={answers[selectedAnswer][1]}
                        activeTab={activeAnalysisPanelTab}
                    />
                )}

                <Panel
                    headerText="Configuration Panel"
                    isOpen={isConfigPanelOpen}
                    isBlocking={false}
                    onDismiss={() => setIsConfigPanelOpen(false)}
                    closeButtonAriaLabel="Close"
                    onRenderFooterContent={() => <DefaultButton onClick={() => setIsConfigPanelOpen(false)}>Close</DefaultButton>}
                    isFooterAtBottom={true}
                >
                    {/* <TextField
                        className={styles.chatSettingsSeparator}
                        defaultValue={promptTemplate}
                        label="Override prompt template"
                        multiline
                        autoAdjustHeight
                        onChange={onPromptTemplateChange}
                    /> */}

                    <div className={styles.spinButtonContainer}>
                        <label className={styles.spinButtonLabel}>Retrieve this many search index results:</label>
                        <SpinButton
                            className={styles.customSpinButton}
                            min={1}
                            max={10}
                            defaultValue={retrieveCount.toString()}
                            onChange={onRetrieveCountChange}
                        />
                    </div>
                    <div className={styles.dropdownContainer}>
                        <label className={styles.includeCategoryLabel}>Include Document Type:</label>
                        <div className={styles.checkboxList}>
                            <button className={styles.toggleButton} onClick={handleToggleCheckAllCategories}>
                                {isAllCategoriesChecked ? "Uncheck All" : "Check All"}
                            </button>

                            {categoryOptions.map(option => (
                                <div key={option.key} className={styles.checkboxItem}>
                                    <input
                                        type="checkbox"
                                        id={`category-option-${option.key}`}
                                        checked={!includeCategory.includes(option.key)}
                                        onChange={() => {
                                            setIncludeCategory(prev =>
                                                prev.includes(option.key) ? prev.filter(key => key !== option.key) : [...prev, option.key]
                                            );
                                        }}
                                    />
                                    <label htmlFor={`category-option-${option.key}`}>{option.text}</label>
                                </div>
                            ))}
                        </div>
                    </div>

                    <div className={styles.dropdownContainer}>
                        <label className={styles.includeCategoryLabel}>Include Epic Version:</label>

                        {/* Dropdown Container */}
                        <div className={styles.dropdown}>
                            {/* Toggle Button */}
                            <button className={styles.toggleButton} onClick={handleToggleCheckAllVersions}>
                                {isAllVersionsChecked ? "Uncheck All" : "Check All"}
                            </button>
                            {/* Dropdown content with checkboxes */}
                            <div className={styles.checkboxList}>
                                {versionOptions.map(option => (
                                    <div key={option.key} className={styles.checkboxItem}>
                                        <input
                                            type="checkbox"
                                            id={`version-option-${option.key}`}
                                            checked={includeVersion.includes(option.key)}
                                            onChange={() => {
                                                setIncludeVersion(prev =>
                                                    prev.includes(option.key) ? prev.filter(key => key !== option.key) : [...prev, option.key]
                                                );
                                            }}
                                        />
                                        <label htmlFor={`version-option-${option.key}`}>{option.text}</label>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>

                    <div className={styles.dropdownContainer}>
                        <label className={styles.includeCategoryLabel}>Include Audience:</label>

                        {/* Search Box */}
                        <input
                            type="text"
                            placeholder="Search Audience..."
                            value={searchTerm}
                            onChange={e => setSearchTerm(e.target.value)}
                            className={styles.searchInput}
                        />

                        {/* Dropdown Container */}
                        <div className={styles.dropdown}>
                            <button className={styles.toggleButton} onClick={handleToggleCheckAllAudience}>
                                {isAllAudienceChecked ? "Uncheck All" : "Check All"}
                            </button>

                            {/* Dropdown content with checkboxes */}
                            <div className={styles.checkboxList}>
                                {displayAudienceOptions.length > 0 ? (
                                    displayAudienceOptions.map(option => (
                                        <div key={option.key} className={styles.checkboxItem}>
                                            <input
                                                type="checkbox"
                                                id={`audience-option-${option.key}`}
                                                checked={includeAudience.includes(option.key)}
                                                onChange={() => {
                                                    setIncludeAudience(prev =>
                                                        prev.includes(option.key) ? prev.filter(key => key !== option.key) : [...prev, option.key]
                                                    );
                                                }}
                                            />
                                            <label htmlFor={`audience-option-${option.key}`}>{option.text}</label>
                                        </div>
                                    ))
                                ) : (
                                    <div className={styles.noResults}>No results found</div>
                                )}
                            </div>
                        </div>
                    </div>
                    {/* <TextField className={styles.chatSettingsSeparator} label="Exclude category" onChange={onExcludeCategoryChanged} />
                    <Checkbox
                        className={styles.chatSettingsSeparator}
                        checked={useSemanticRanker}
                        label="Use semantic ranker for retrieval"
                        onChange={onUseSemanticRankerChange}
                    />
                    <Checkbox
                        className={styles.chatSettingsSeparator}
                        checked={useSemanticCaptions}
                        label="Use query-contextual summaries instead of whole documents"
                        onChange={onUseSemanticCaptionsChange}
                        disabled={!useSemanticRanker}
                    />
                    <Checkbox
                        className={styles.chatSettingsSeparator}
                        checked={useSuggestFollowupQuestions}
                        label="Suggest follow-up questions"
                        onChange={onUseSuggestFollowupQuestionsChange}
                    />

                    {showGPT4VOptions && (
                        <GPT4VSettings
                            gpt4vInputs={gpt4vInput}
                            isUseGPT4V={useGPT4V}
                            updateUseGPT4V={useGPT4V => {
                                setUseGPT4V(useGPT4V);
                            }}
                            updateGPT4VInputs={inputs => setGPT4VInput(inputs)}
                        />
                    )}

                    <VectorSettings
                        showImageOptions={useGPT4V && showGPT4VOptions}
                        updateVectorFields={(options: VectorFieldOptions[]) => setVectorFieldList(options)}
                        updateRetrievalMode={(retrievalMode: RetrievalMode) => setRetrievalMode(retrievalMode)}
                    /> */}

                    {useLogin && (
                        <Checkbox
                            className={styles.chatSettingsSeparator}
                            checked={useOidSecurityFilter || requireAccessControl}
                            label="Use oid security filter"
                            disabled={!isLoggedIn(client) || requireAccessControl}
                            onChange={onUseOidSecurityFilterChange}
                        />
                    )}
                    {useLogin && (
                        <Checkbox
                            className={styles.chatSettingsSeparator}
                            checked={useGroupsSecurityFilter || requireAccessControl}
                            label="Use groups security filter"
                            disabled={!isLoggedIn(client) || requireAccessControl}
                            onChange={onUseGroupsSecurityFilterChange}
                        />
                    )}

                    {/* <Checkbox
                        className={styles.chatSettingsSeparator}
                        checked={shouldStream}
                        label="Stream chat completion responses"
                        onChange={onShouldStreamChange}
                    /> */}
                    {useLogin && <TokenClaimsDisplay />}
                </Panel>
            </div>
        </div>
    );
};

export default Chat;
