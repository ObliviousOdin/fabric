import SwiftUI
import UIKit

/// Renders a security-sensitive endpoint without allowing the text engine to
/// invent visible hyphens inside its host name. Character wrapping keeps the
/// exact endpoint readable at accessibility sizes while selection and
/// VoiceOver continue to expose the unmodified source string.
struct GatewayEndpointIdentityText: UIViewRepresentable {
    enum Style {
        case caption
        case footnote
        case subheadline

        fileprivate var textStyle: UIFont.TextStyle {
            switch self {
            case .caption: .caption1
            case .footnote: .footnote
            case .subheadline: .subheadline
            }
        }
    }

    let endpoint: String
    let style: Style
    let selectable: Bool

    init(endpoint: String, style: Style, selectable: Bool = true) {
        self.endpoint = endpoint
        self.style = style
        self.selectable = selectable
    }

    func makeUIView(context: Context) -> UITextView {
        let textView = UITextView()
        textView.backgroundColor = .clear
        textView.isEditable = false
        textView.isSelectable = selectable
        textView.isUserInteractionEnabled = selectable
        textView.isScrollEnabled = false
        textView.textContainerInset = .zero
        textView.textContainer.lineFragmentPadding = 0
        textView.textContainer.lineBreakMode = .byCharWrapping
        textView.layoutManager.usesDefaultHyphenation = false
        textView.adjustsFontForContentSizeCategory = true
        textView.setContentHuggingPriority(.defaultLow, for: .horizontal)
        textView.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        return textView
    }

    func updateUIView(_ textView: UITextView, context: Context) {
        let preferred = UIFont.preferredFont(forTextStyle: style.textStyle)
        let descriptor = preferred.fontDescriptor.withDesign(.monospaced)
            ?? preferred.fontDescriptor
        let paragraph = NSMutableParagraphStyle()
        paragraph.hyphenationFactor = 0
        paragraph.usesDefaultHyphenation = false
        paragraph.lineBreakStrategy = []
        paragraph.lineBreakMode = .byCharWrapping

        textView.attributedText = NSAttributedString(
            string: endpoint,
            attributes: [
                .font: UIFont(descriptor: descriptor, size: 0),
                .foregroundColor: UIColor(FabricTheme.textMuted),
                .paragraphStyle: paragraph,
            ]
        )
        textView.isSelectable = selectable
        textView.isUserInteractionEnabled = selectable
        textView.accessibilityLabel = endpoint
        textView.accessibilityTraits = .staticText
    }

    func sizeThatFits(
        _ proposal: ProposedViewSize,
        uiView: UITextView,
        context: Context
    ) -> CGSize? {
        guard let width = proposal.width else { return nil }
        let measured = uiView.sizeThatFits(
            CGSize(width: width, height: CGFloat.greatestFiniteMagnitude)
        )
        return CGSize(width: width, height: ceil(measured.height))
    }
}
